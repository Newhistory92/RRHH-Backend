# Productividad configurable sobre LogSistema — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que un administrador tilde en una pantalla qué rutas del sistema de gestión cuentan como trabajo, y que el score de productividad se calcule sobre esa decisión leyendo `LogSistema` en vez de la fuente actual, que registra altas de permisos y no trabajo.

**Architecture:** Una función pura normaliza URLs a rutas canónicas (colapsa IDs y query strings). Una tabla nueva en la base de RRHH guarda qué rutas cuentan. Tres endpoints bajo `admin.gestionar` exponen el catálogo, el guardado en lote y el explorador de logs crudos. El cálculo del score cambia de fuente y filtra por la configuración, registrándose como fórmula nueva para no mezclar historiales.

**Tech Stack:** FastAPI, SQLAlchemy Core (`text()`), SQL Server vía pyodbc, pytest. Frontend Next.js 15 App Router con Tailwind y PrimeReact.

## Global Constraints

- **Nunca escribir en la base ObraSocial.** Todo acceso a `[ObraSocial].[dbo].*` es de sólo lectura: SELECT únicamente. La tabla de configuración va en la base de RRHH.
- Cero IDs de rol hardcodeados en frontend logic o backend. La autorización siempre vía `require_permission(...)`.
- Los archivos `.env` nunca se commitean, se copian ni se muestran.
- Comentarios y docstrings en castellano sin tildes, siguiendo el estilo del repositorio.
- Los comentarios explican *por qué*, no *qué*. El código ya dice qué hace.
- Baseline del frontend: `npx tsc --noEmit` devuelve **27 errores** preexistentes. Ninguna tarea puede aumentar ese número.
- Baseline del backend: `pytest -q` devuelve **405 passed**. Cada tarea suma tests y ninguna puede romper los existentes.
- `MARGEN_DESEMPATE`, `VENTANA_MESES = 12` y toda la cadena de exentos, vinculación por DNI y horas del reloj **no se tocan**.

---

## Estructura de archivos

**Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)**

| Archivo | Responsabilidad |
|---|---|
| `app/services/normalizar_ruta.py` | Crear. Función pura URL cruda → ruta canónica |
| `app/database/rutas_productividad.py` | Crear. DDL de `RutaProductividad` y acceso a datos |
| `app/routes/logs_productividad.py` | Crear. Los tres endpoints + recálculo manual |
| `app/database/score_historico.py` | Modificar. Agregar `FORMULA_LOGSISTEMA` |
| `app/routes/stats.py` | Modificar. `calculate_productivity_scores` cambia de fuente |
| `app/main.py` | Modificar. Registrar el router nuevo |
| `tests/test_normalizar_ruta.py` | Crear |
| `tests/test_rutas_productividad.py` | Crear |
| `tests/test_logs_endpoints.py` | Crear |
| `tests/test_score_logsistema.py` | Crear |

**Frontend (`C:\Users\Emiliano\Documents\RRHH`)**

| Archivo | Responsabilidad |
|---|---|
| `src/app/Componentes/Admin/ProductividadTab.tsx` | Crear. Contenedor con las dos sub-vistas |
| `src/app/Componentes/Admin/RutasProductividad.tsx` | Crear. Tabla tildable |
| `src/app/Componentes/Admin/LogsExplorer.tsx` | Crear. Explorador crudo |
| `src/app/Interfas/Interfaces.ts` | Modificar. Tipos `RutaProductividad` y `LogSistemaFila` |
| `src/app/screens/Admin/Screen.tsx` | Modificar. Agregar el tab |

---

### Task 1: Normalización de rutas

**Files:**
- Create: `app/services/normalizar_ruta.py`
- Test: `tests/test_normalizar_ruta.py`

**Interfaces:**
- Consumes: nada.
- Produces: `normalizar_ruta(url: str) -> str`. Usada por las Tasks 3 y 6.

**Contexto:** Las URLs crudas de `LogSistema` dan 8.514 combinaciones distintas de método+URL porque llevan IDs y query strings. Normalizadas quedan 1.830. Sin esta función el checkbox es inviable.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_normalizar_ruta.py`:

```python
"""
Tests de la normalizacion de URLs a rutas canonicas.

Los casos salen de datos reales de LogSistema medidos el 2026-09-02.
"""

import pytest

from app.services.normalizar_ruta import normalizar_ruta


@pytest.mark.parametrize("cruda, esperada", [
    # Rutas simples: no cambian
    ("/usuario/login-app", "/usuario/login-app"),
    ("/afiliado/nueva-consulta", "/afiliado/nueva-consulta"),
    ("/", "/"),
    # Query string: se descarta
    ("/orden/buscar?dni=30111222", "/orden/buscar"),
    ("/afiliado?x=1&y=2", "/afiliado"),
    # Segmento numerico: colapsa
    ("/orden/123", "/orden/:id"),
    ("/orden/123/detalle", "/orden/:id/detalle"),
    ("/cron/456", "/cron/:id"),
    # GUID: colapsa
    ("/files/afiliado/f8ee8d1a-b978-4caa-8063-cdbe3032c711",
     "/files/afiliado/:id"),
    # Combinado: ID en el medio y query string
    ("/orden/789/historial?desde=2026-01-01", "/orden/:id/historial"),
    # Varios IDs
    ("/afiliado/12/grupo/34", "/afiliado/:id/grupo/:id"),
])
def test_normaliza(cruda, esperada):
    assert normalizar_ruta(cruda) == esperada


def test_string_vacio_devuelve_barra():
    """Una URL vacia no debe romper el agregado ni generar una ruta ''."""
    assert normalizar_ruta("") == "/"


def test_none_devuelve_barra():
    """LogSistema.url es nullable; None no puede propagar un TypeError."""
    assert normalizar_ruta(None) == "/"


def test_no_colapsa_palabras_con_numeros():
    """'v2' o 'covid19' son nombres de recurso, no identificadores."""
    assert normalizar_ruta("/api/v2/afiliado") == "/api/v2/afiliado"


def test_es_idempotente():
    """Normalizar dos veces debe dar lo mismo: el catalogo se recalcula
    en cada request y una ruta ya normalizada no puede volver a cambiar."""
    una_vez = normalizar_ruta("/orden/123?x=1")
    assert normalizar_ruta(una_vez) == una_vez
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_normalizar_ruta.py -q
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.services.normalizar_ruta'`.

- [ ] **Step 3: Implementar**

Crear `app/services/normalizar_ruta.py`:

```python
"""
Normalizacion de URLs crudas a rutas canonicas.

LogSistema guarda la URL tal cual llego, con el id del recurso adentro y el
query string pegado. Eso da 8.514 combinaciones distintas de metodo+URL, que
es imposible de clasificar a mano. Colapsando los identificadores quedan
1.830, y las 25 primeras concentran el 79% del volumen.

Funcion pura, sin I/O: es la unidad que decide que es "la misma ruta" para
toda la aplicacion, asi que tiene que ser testeable sin base.
"""

import re

# Un GUID canonico. Se ancla a los extremos para no matchear un segmento que
# apenas contenga algo con esa forma.
GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _es_identificador(segmento: str) -> bool:
    """
    Un segmento es identificador si es todo digitos o un GUID.

    Deliberadamente NO se colapsa cualquier cosa que contenga numeros: 'v2' y
    'covid19' son nombres de recurso y colapsarlos fusionaria rutas distintas
    en una sola fila del catalogo.
    """
    return segmento.isdigit() or bool(GUID.match(segmento))


def normalizar_ruta(url: str | None) -> str:
    """
    Devuelve la ruta canonica de una URL cruda.

    Descarta el query string y reemplaza por ':id' los segmentos que son
    identificadores, de modo que /orden/123 y /orden/456 sean la misma ruta.
    """
    if not url:
        return "/"

    sin_query = url.split("?", 1)[0]
    if not sin_query:
        return "/"

    partes = [
        ":id" if _es_identificador(p) else p
        for p in sin_query.split("/")
    ]
    return "/".join(partes) or "/"
```

- [ ] **Step 4: Correr el test para verificar que pasa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_normalizar_ruta.py -q
```

Esperado: `17 passed`.

- [ ] **Step 5: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest -q
```

Esperado: `422 passed` (405 previos + 17 nuevos).

- [ ] **Step 6: Commit**

```bash
git add app/services/normalizar_ruta.py tests/test_normalizar_ruta.py
git commit -m "feat(logs): normalizacion de URLs a rutas canonicas"
```

---

### Task 2: Tabla RutaProductividad y capa de datos

**Files:**
- Create: `app/database/rutas_productividad.py`
- Test: `tests/test_rutas_productividad.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `ensure_table(db: Session) -> None`
  - `configuracion_actual(db: Session) -> dict[tuple[str, str], float]` — clave `(metodo, ruta)`, valor `peso`
  - `rutas_habilitadas(db: Session) -> set[tuple[str, str]]` — sólo las de `peso > 0`
  - `upsert_rutas(db: Session, filas: list[dict], clasificado_por: int | None) -> int` — cada fila es `{"metodo": str, "ruta": str, "cuenta": bool}`; devuelve cuántas filas escribió

**Contexto:** La configuración vive en la base de RRHH porque ObraSocial es de sólo lectura sin excepción. La columna es `peso DECIMAL(5,2)` y no un `BIT` para que la etapa futura de pesos no requiera migrar datos.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_rutas_productividad.py`:

```python
"""
Tests de la capa de datos de RutaProductividad.

FakeSession no ejecuta SQL: verifica que se emitan las sentencias correctas
con los binds correctos, y que las funciones traduzcan bien las filas.
"""

from app.database.rutas_productividad import (
    configuracion_actual,
    ensure_table,
    rutas_habilitadas,
    upsert_rutas,
)
from tests.fakes import FakeSession


def test_ensure_table_crea_tabla_en_rrhh_no_en_obrasocial():
    """La configuracion vive en RRHH: ObraSocial es de solo lectura."""
    db = FakeSession()
    ensure_table(db)
    sql = db.sql_ejecutado()
    assert "RutaProductividad" in sql
    assert "ObraSocial" not in sql


def test_ensure_table_es_repetible():
    """Se llama en cada request del catalogo; no puede fallar la segunda vez."""
    db = FakeSession()
    ensure_table(db)
    assert "IF OBJECT_ID" in db.sql_ejecutado()


def test_configuracion_actual_mapea_por_metodo_y_ruta():
    db = FakeSession({"FROM RutaProductividad": [
        {"metodo": "POST", "ruta": "/afiliado/nueva-consulta", "peso": 1.0},
        {"metodo": "POST", "ruta": "/usuario/login", "peso": 0.0},
    ]})
    assert configuracion_actual(db) == {
        ("POST", "/afiliado/nueva-consulta"): 1.0,
        ("POST", "/usuario/login"): 0.0,
    }


def test_rutas_habilitadas_excluye_peso_cero():
    """Peso 0 es 'alguien decidio que no cuenta', y no debe sumar."""
    db = FakeSession({"FROM RutaProductividad": [
        {"metodo": "POST", "ruta": "/afiliado/nueva-consulta", "peso": 1.0},
        {"metodo": "POST", "ruta": "/usuario/login", "peso": 0.0},
    ]})
    assert rutas_habilitadas(db) == {("POST", "/afiliado/nueva-consulta")}


def test_upsert_escribe_peso_1_cuando_cuenta_es_true():
    db = FakeSession()
    upsert_rutas(db, [
        {"metodo": "POST", "ruta": "/afiliado/nueva-consulta", "cuenta": True},
    ], clasificado_por=7)
    _sql, params = db.ejecutadas[-1]
    assert params[0]["peso"] == 1
    assert params[0]["clasificadoPor"] == 7


def test_upsert_escribe_peso_0_cuando_cuenta_es_false():
    db = FakeSession()
    upsert_rutas(db, [
        {"metodo": "POST", "ruta": "/usuario/login", "cuenta": False},
    ], clasificado_por=7)
    _sql, params = db.ejecutadas[-1]
    assert params[0]["peso"] == 0


def test_upsert_devuelve_cantidad_escrita():
    db = FakeSession()
    escritas = upsert_rutas(db, [
        {"metodo": "POST", "ruta": "/a", "cuenta": True},
        {"metodo": "GET", "ruta": "/b", "cuenta": False},
    ], clasificado_por=None)
    assert escritas == 2


def test_upsert_con_lista_vacia_no_ejecuta_nada():
    """Guardar sin cambios no debe abrir una transaccion inutil."""
    db = FakeSession()
    escritas = upsert_rutas(db, [], clasificado_por=1)
    assert escritas == 0
    assert db.ejecutadas == []
    assert db.commits == 0


def test_upsert_usa_merge_para_no_duplicar():
    """La clave (metodo, ruta) es unica: reclasificar actualiza, no inserta."""
    db = FakeSession()
    upsert_rutas(db, [{"metodo": "POST", "ruta": "/a", "cuenta": True}],
                 clasificado_por=1)
    sql = db.sql_ejecutado()
    assert "MERGE" in sql.upper()
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_rutas_productividad.py -q
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.database.rutas_productividad'`.

- [ ] **Step 3: Implementar**

Crear `app/database/rutas_productividad.py`:

```python
"""
Que rutas del sistema de gestion cuentan como trabajo para el score.

Vive en la base de RRHH y no en ObraSocial: esa base es de solo lectura sin
excepcion, y ademas la decision de que cuenta es de RRHH, no del sistema que
genera los logs.

La columna es un decimal y no un bit aunque la interfaz de esta etapa sea un
checkbox. El dia que se quiera decir que crear una internacion vale 3 y buscar
vale 1, es cambiar la UI: ni migracion de datos ni reescritura del calculo.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_TABLE_SQL = """
IF OBJECT_ID('RutaProductividad', 'U') IS NULL
CREATE TABLE RutaProductividad (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    metodo         NVARCHAR(10)  NOT NULL,
    ruta           NVARCHAR(500) NOT NULL,
    peso           DECIMAL(5,2)  NOT NULL DEFAULT 0,
    clasificadoPor INT           NULL,
    clasificadoEn  DATETIME2     NULL,
    notas          NVARCHAR(500) NULL,
    CONSTRAINT UQ_RutaProductividad_metodo_ruta UNIQUE (metodo, ruta)
);
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def configuracion_actual(db: Session) -> dict[tuple[str, str], float]:
    """
    Toda la configuracion guardada, indexada por (metodo, ruta).

    Que una ruta NO aparezca aca significa "pendiente de clasificar", que es
    un estado distinto de "clasificada en cero": las dos no suman al score,
    pero solo la primera tiene que aparecerle al administrador como novedad.
    """
    filas = db.execute(text("""
        SELECT metodo, ruta, peso
        FROM RutaProductividad
    """)).mappings().all()
    return {(f["metodo"], f["ruta"]): float(f["peso"]) for f in filas}


def rutas_habilitadas(db: Session) -> set[tuple[str, str]]:
    """Las rutas que suman al score. Es lo que consume el calculo."""
    return {
        clave for clave, peso in configuracion_actual(db).items() if peso > 0
    }


def upsert_rutas(
    db: Session,
    filas: list[dict],
    clasificado_por: int | None,
) -> int:
    """
    Guarda una tanda de clasificaciones.

    Cada fila es {"metodo", "ruta", "cuenta"}. El booleano se traduce a peso
    1 o 0; la API expone el booleano porque la interfaz de esta etapa es
    binaria, y la tabla guarda el decimal para no atarse a eso.

    Es MERGE y no INSERT porque reclasificar una ruta ya vista es el caso
    normal, y la clave (metodo, ruta) es unica.
    """
    if not filas:
        return 0

    db.execute(
        text("""
            MERGE RutaProductividad AS destino
            USING (SELECT :metodo AS metodo, :ruta AS ruta) AS origen
                ON destino.metodo = origen.metodo AND destino.ruta = origen.ruta
            WHEN MATCHED THEN
                UPDATE SET peso = :peso,
                           clasificadoPor = :clasificadoPor,
                           clasificadoEn = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (metodo, ruta, peso, clasificadoPor, clasificadoEn)
                VALUES (:metodo, :ruta, :peso, :clasificadoPor, GETDATE());
        """),
        [
            {
                "metodo": f["metodo"],
                "ruta": f["ruta"],
                "peso": 1 if f.get("cuenta") else 0,
                "clasificadoPor": clasificado_por,
            }
            for f in filas
        ],
    )
    db.commit()
    return len(filas)
```

- [ ] **Step 4: Correr el test para verificar que pasa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_rutas_productividad.py -q
```

Esperado: `9 passed`.

- [ ] **Step 5: Verificar el DDL contra la base real**

El patrón `FakeSession` no ejecuta SQL, así que el DDL hay que probarlo de verdad. Ya hubo en este repositorio un caso de columna mal nombrada que los tests no detectaron.

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -c "
from app.database.database import SessionLocal
from app.database.rutas_productividad import ensure_table, configuracion_actual
db = SessionLocal()
ensure_table(db)
print('tabla creada, configuracion actual:', configuracion_actual(db))
db.close()
"
```

Esperado: `tabla creada, configuracion actual: {}` sin excepción.

- [ ] **Step 6: Commit**

```bash
git add app/database/rutas_productividad.py tests/test_rutas_productividad.py
git commit -m "feat(logs): tabla RutaProductividad y capa de datos"
```

---

### Task 3: Endpoint del catálogo de rutas

**Files:**
- Create: `app/routes/logs_productividad.py`
- Modify: `app/main.py`
- Test: `tests/test_logs_endpoints.py`

**Interfaces:**
- Consumes: `normalizar_ruta` (Task 1); `ensure_table`, `configuracion_actual` (Task 2).
- Produces:
  - `router` con prefijo `/admin/logs`, registrado en `main.py`
  - `armar_catalogo(agregado: list[dict], config: dict[tuple[str, str], float]) -> list[dict]` — función pura, reutilizada por los tests
  - `GET /admin/logs/rutas`

**Contexto:** El agregado sale de ObraSocial (sólo SELECT) y la configuración de RRHH. Como son bases distintas no se pueden unir en una consulta, así que el cruce ocurre en Python. La normalización también, porque duplicar la lógica en T-SQL la volvería imposible de mantener en sincronía con la función pura de la Task 1.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_logs_endpoints.py`:

```python
"""
Tests de los endpoints de /admin/logs.

Los handlers se invocan directamente, sin servidor HTTP, siguiendo el patron
del resto de la suite.
"""

from app.routes.logs_productividad import armar_catalogo


def test_ruta_sin_configuracion_queda_pendiente():
    """Nada entra al score sin decision humana: lo no clasificado es
    'pendiente', no 'no cuenta'."""
    catalogo = armar_catalogo(
        agregado=[{"metodo": "POST", "url": "/afiliado/nueva-consulta",
                   "eventos": 10, "usuarios": 3, "ultimaVez": "2026-09-01"}],
        config={},
    )
    assert catalogo[0]["estado"] == "pendiente"


def test_ruta_con_peso_positivo_cuenta():
    catalogo = armar_catalogo(
        agregado=[{"metodo": "POST", "url": "/afiliado/nueva-consulta",
                   "eventos": 10, "usuarios": 3, "ultimaVez": "2026-09-01"}],
        config={("POST", "/afiliado/nueva-consulta"): 1.0},
    )
    assert catalogo[0]["estado"] == "cuenta"


def test_ruta_con_peso_cero_no_cuenta_y_no_es_pendiente():
    """Peso 0 es una decision tomada: no debe reaparecer como novedad."""
    catalogo = armar_catalogo(
        agregado=[{"metodo": "POST", "url": "/usuario/login",
                   "eventos": 99, "usuarios": 50, "ultimaVez": "2026-09-01"}],
        config={("POST", "/usuario/login"): 0.0},
    )
    assert catalogo[0]["estado"] == "no_cuenta"


def test_urls_con_distinto_id_colapsan_en_una_fila():
    """Sin esto habria 8.514 filas que tildar en vez de 1.830."""
    catalogo = armar_catalogo(
        agregado=[
            {"metodo": "GET", "url": "/orden/123", "eventos": 5,
             "usuarios": 2, "ultimaVez": "2026-09-01"},
            {"metodo": "GET", "url": "/orden/456", "eventos": 7,
             "usuarios": 3, "ultimaVez": "2026-09-02"},
        ],
        config={},
    )
    assert len(catalogo) == 1
    assert catalogo[0]["ruta"] == "/orden/:id"
    assert catalogo[0]["eventos"] == 12


def test_al_colapsar_se_toma_la_ultima_fecha():
    catalogo = armar_catalogo(
        agregado=[
            {"metodo": "GET", "url": "/orden/123", "eventos": 5,
             "usuarios": 2, "ultimaVez": "2026-08-01"},
            {"metodo": "GET", "url": "/orden/456", "eventos": 7,
             "usuarios": 3, "ultimaVez": "2026-09-02"},
        ],
        config={},
    )
    assert catalogo[0]["ultimaVez"] == "2026-09-02"


def test_mismo_path_distinto_metodo_son_filas_distintas():
    """GET /orden y POST /orden no son la misma accion."""
    catalogo = armar_catalogo(
        agregado=[
            {"metodo": "GET", "url": "/orden", "eventos": 5,
             "usuarios": 2, "ultimaVez": "2026-09-01"},
            {"metodo": "POST", "url": "/orden", "eventos": 3,
             "usuarios": 1, "ultimaVez": "2026-09-01"},
        ],
        config={},
    )
    assert len(catalogo) == 2


def test_catalogo_ordenado_por_volumen_descendente():
    """El administrador tilda de arriba hacia abajo: las 25 primeras rutas
    concentran el 79% del volumen."""
    catalogo = armar_catalogo(
        agregado=[
            {"metodo": "GET", "url": "/poco", "eventos": 5,
             "usuarios": 1, "ultimaVez": "2026-09-01"},
            {"metodo": "GET", "url": "/mucho", "eventos": 500,
             "usuarios": 40, "ultimaVez": "2026-09-01"},
        ],
        config={},
    )
    assert [f["ruta"] for f in catalogo] == ["/mucho", "/poco"]


def test_agregado_vacio_devuelve_lista_vacia():
    """Si ObraSocial no responde, la pantalla no puede romperse."""
    assert armar_catalogo(agregado=[], config={}) == []
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_logs_endpoints.py -q
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.routes.logs_productividad'`.

- [ ] **Step 3: Implementar el router y el catálogo**

Crear `app/routes/logs_productividad.py`:

```python
"""
Administracion de que actividad del sistema de gestion cuenta como trabajo.

El score se calculaba sobre UsuarioAccesoLogs, que registra altas y bajas de
permisos y no trabajo de nadie. La actividad real esta en LogSistema, pero
cruda incluye login, refresh de token y polling, que no son trabajo. Estos
endpoints permiten decidir cual es cual.

Todo acceso a ObraSocial es SELECT. La configuracion se guarda en RRHH.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import require_permission
from app.database.database import SessionLocal, SessionLocalObraSocial
from app.database.rutas_productividad import (
    configuracion_actual,
    ensure_table,
)
from app.services.normalizar_ruta import normalizar_ruta

router = APIRouter(
    prefix="/admin/logs",
    tags=["Logs productividad"],
    dependencies=[Depends(require_permission("admin.gestionar"))],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_logs_db():
    db = SessionLocalObraSocial()
    try:
        yield db
    finally:
        db.close()


def armar_catalogo(
    agregado: list[dict],
    config: dict[tuple[str, str], float],
) -> list[dict]:
    """
    Cruza la actividad observada con la configuracion guardada.

    El agregado viene con URLs crudas, una fila por URL distinta; aca se las
    normaliza y se suman las que colapsan en la misma ruta. El cruce ocurre en
    Python y no en SQL porque las dos tablas viven en bases distintas, y la
    normalizacion tambien, para no tener la misma logica escrita dos veces en
    dos lenguajes.

    Funcion pura, sin I/O.
    """
    acumulado: dict[tuple[str, str], dict] = {}

    for fila in agregado:
        clave = (fila["metodo"], normalizar_ruta(fila["url"]))
        actual = acumulado.get(clave)
        if actual is None:
            acumulado[clave] = {
                "metodo": clave[0],
                "ruta": clave[1],
                "eventos": fila["eventos"],
                # Es el maximo por URL cruda y no el distinct real del grupo:
                # sumarlos contaria dos veces a quien uso varias URLs de la
                # misma ruta, y eso exageraria el alcance de la ruta.
                "usuarios": fila["usuarios"],
                "ultimaVez": fila["ultimaVez"],
            }
        else:
            actual["eventos"] += fila["eventos"]
            actual["usuarios"] = max(actual["usuarios"], fila["usuarios"])
            actual["ultimaVez"] = max(actual["ultimaVez"], fila["ultimaVez"])

    catalogo = []
    for clave, datos in acumulado.items():
        peso = config.get(clave)
        if peso is None:
            estado = "pendiente"
        elif peso > 0:
            estado = "cuenta"
        else:
            estado = "no_cuenta"
        catalogo.append({**datos, "estado": estado})

    catalogo.sort(key=lambda f: f["eventos"], reverse=True)
    return catalogo


AGREGADO_SQL = text("""
    SELECT
        metodo,
        url,
        COUNT(*) AS eventos,
        COUNT(DISTINCT idUsuario) AS usuarios,
        CONVERT(VARCHAR(10), MAX(fechaHoraLog), 23) AS ultimaVez
    FROM [ObraSocial].[dbo].[LogSistema]
    WHERE fechaHoraLog >= DATEADD(MONTH, -:meses, GETDATE())
      AND idUsuario IS NOT NULL
      AND statusCode >= 200 AND statusCode < 300
    GROUP BY metodo, url
""")


@router.get("/rutas")
def listar_rutas(
    meses: int = 12,
    db: Session = Depends(get_db),
    logs_db: Session = Depends(get_logs_db),
):
    """
    Catalogo de rutas observadas con su estado de clasificacion.

    Si ObraSocial no responde se devuelve la configuracion guardada sin
    volumen, en vez de un error: la clasificacion vive en RRHH y se puede
    seguir trabajando sin la otra base.
    """
    ensure_table(db)
    config = configuracion_actual(db)

    try:
        filas = logs_db.execute(
            AGREGADO_SQL, {"meses": meses}
        ).mappings().all()
        agregado = [dict(f) for f in filas]
        actividad_disponible = True
    except Exception:
        agregado = []
        actividad_disponible = False

    catalogo = armar_catalogo(agregado, config)

    # Las rutas ya clasificadas que no aparecieron en la ventana siguen siendo
    # parte de la configuracion y tienen que poder des-clasificarse.
    vistas = {(f["metodo"], f["ruta"]) for f in catalogo}
    for (metodo, ruta), peso in config.items():
        if (metodo, ruta) not in vistas:
            catalogo.append({
                "metodo": metodo,
                "ruta": ruta,
                "eventos": 0,
                "usuarios": 0,
                "ultimaVez": None,
                "estado": "cuenta" if peso > 0 else "no_cuenta",
            })

    return {
        "rutas": catalogo,
        "actividadDisponible": actividad_disponible,
        "pendientes": sum(1 for f in catalogo if f["estado"] == "pendiente"),
    }
```

- [ ] **Step 4: Registrar el router**

En `app/main.py:16` hay un único import de línea larga con todos los routers. Agregar `logs_productividad` al final de esa lista:

```python
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion, publications, activos_config, activos, activos_modelos, relojes, asistencia, asistencia_ausencias, chat, logs_productividad
```

Y agregar la línea de registro inmediatamente después de `app.include_router(stats.router)` (línea 100):

```python
app.include_router(logs_productividad.router)
```

- [ ] **Step 5: Correr los tests**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_logs_endpoints.py -q
```

Esperado: `8 passed`.

- [ ] **Step 6: Verificar la consulta contra la base real**

`FakeSession` no ejecuta SQL, así que los nombres de columna contra ObraSocial se verifican aparte.

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -c "
from app.database.database import SessionLocalObraSocial
from app.routes.logs_productividad import AGREGADO_SQL
db = SessionLocalObraSocial()
filas = db.execute(AGREGADO_SQL, {'meses': 12}).mappings().all()
print('filas del agregado:', len(filas))
print('primera:', dict(filas[0]) if filas else 'sin datos')
db.close()
"
```

Esperado: alrededor de 5.000 filas y una primera fila con las claves `metodo`, `url`, `eventos`, `usuarios`, `ultimaVez`. Si falla por nombre de columna, corregir contra `INFORMATION_SCHEMA.COLUMNS` de `LogSistema`.

- [ ] **Step 7: Correr la suite completa y commitear**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest -q
```

Esperado: `430 passed`.

```bash
git add app/routes/logs_productividad.py app/main.py tests/test_logs_endpoints.py
git commit -m "feat(logs): endpoint del catalogo de rutas con estado de clasificacion"
```

---

### Task 4: Endpoint de guardado en lote

**Files:**
- Modify: `app/routes/logs_productividad.py`
- Test: `tests/test_logs_endpoints.py`

**Interfaces:**
- Consumes: `upsert_rutas`, `ensure_table` (Task 2); el `router` de la Task 3.
- Produces: `PUT /admin/logs/rutas`, con el modelo `ClasificacionRequest`.

**Contexto:** El flujo real es tildar veinte rutas de una pasada. Un request por fila multiplicaría los viajes sin dar nada a cambio.

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_logs_endpoints.py`:

```python
from app.routes.logs_productividad import (
    ClasificacionRequest,
    RutaClasificada,
    guardar_rutas,
)
from tests.fakes import FakeSession


def test_guardar_persiste_las_filas_recibidas():
    db = FakeSession()
    payload = ClasificacionRequest(rutas=[
        RutaClasificada(metodo="POST", ruta="/afiliado/nueva-consulta",
                        cuenta=True),
        RutaClasificada(metodo="POST", ruta="/usuario/login", cuenta=False),
    ])
    resultado = guardar_rutas(payload=payload, db=db, employee_id=5)
    assert resultado == {"success": True, "guardadas": 2}


def test_guardar_registra_quien_clasifico():
    """Una decision que cambia scores de ascenso tiene que ser trazable."""
    db = FakeSession()
    payload = ClasificacionRequest(rutas=[
        RutaClasificada(metodo="POST", ruta="/a", cuenta=True),
    ])
    guardar_rutas(payload=payload, db=db, employee_id=42)
    _sql, params = db.ejecutadas[-1]
    assert params[0]["clasificadoPor"] == 42


def test_guardar_lista_vacia_no_falla():
    db = FakeSession()
    resultado = guardar_rutas(
        payload=ClasificacionRequest(rutas=[]), db=db, employee_id=1
    )
    assert resultado == {"success": True, "guardadas": 0}


def test_guardar_nunca_escribe_en_obrasocial():
    """Restriccion dura del proyecto: esa base es de solo lectura."""
    db = FakeSession()
    guardar_rutas(
        payload=ClasificacionRequest(rutas=[
            RutaClasificada(metodo="POST", ruta="/a", cuenta=True),
        ]),
        db=db, employee_id=1,
    )
    assert "ObraSocial" not in db.sql_ejecutado()
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_logs_endpoints.py -q
```

Esperado: FAIL con `ImportError: cannot import name 'ClasificacionRequest'`.

- [ ] **Step 3: Implementar**

En `app/routes/logs_productividad.py`, agregar el import de `upsert_rutas` a la lista existente:

```python
from app.database.rutas_productividad import (
    configuracion_actual,
    ensure_table,
    upsert_rutas,
)
```

Y agregar al final del archivo:

```python
class RutaClasificada(BaseModel):
    metodo: str
    ruta: str
    cuenta: bool


class ClasificacionRequest(BaseModel):
    rutas: list[RutaClasificada]


@router.put("/rutas")
def guardar_rutas(
    payload: ClasificacionRequest,
    db: Session = Depends(get_db),
    employee_id: int | None = None,
):
    """
    Guarda una tanda de clasificaciones.

    Recibe el lote entero y no una ruta por request porque el flujo real es
    tildar veinte de una pasada. Queda registrado quien clasifico: esto mueve
    scores que se usan para decidir ascensos, y tiene que ser trazable.
    """
    ensure_table(db)
    guardadas = upsert_rutas(
        db,
        [f.model_dump() for f in payload.rutas],
        clasificado_por=employee_id,
    )
    return {"success": True, "guardadas": guardadas}
```

- [ ] **Step 4: Correr los tests**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_logs_endpoints.py -q
```

Esperado: `12 passed`.

- [ ] **Step 5: Correr la suite completa y commitear**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest -q
```

Esperado: `434 passed`.

```bash
git add app/routes/logs_productividad.py tests/test_logs_endpoints.py
git commit -m "feat(logs): guardado en lote de la clasificacion de rutas"
```

---

### Task 5: Explorador de logs crudos

**Files:**
- Modify: `app/routes/logs_productividad.py`
- Test: `tests/test_logs_endpoints.py`

**Interfaces:**
- Consumes: el `router` y `get_logs_db` de la Task 3.
- Produces: `GET /admin/logs`, y la función pura `construir_filtros(filtros: dict) -> tuple[str, dict]` que arma el WHERE y sus binds.

**Contexto:** Sin poder mirar los logs crudos, se tildan a ciegas rutas cuyo nombre no alcanza para entender qué son.

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_logs_endpoints.py`:

```python
from app.routes.logs_productividad import construir_filtros


def test_sin_filtros_solo_excluye_nada():
    where, binds = construir_filtros({})
    assert where == ""
    assert binds == {}


def test_filtro_por_metodo():
    where, binds = construir_filtros({"metodo": "POST"})
    assert "metodo = :metodo" in where
    assert binds["metodo"] == "POST"


def test_filtro_por_texto_en_url_usa_like():
    where, binds = construir_filtros({"texto": "afiliado"})
    assert "url LIKE :texto" in where
    assert binds["texto"] == "%afiliado%"


def test_filtro_por_clase_de_status_exito():
    where, binds = construir_filtros({"clase": "exito"})
    assert "statusCode >= 200" in where and "statusCode < 300" in where


def test_filtro_por_clase_de_status_error_cliente():
    where, _binds = construir_filtros({"clase": "error_cliente"})
    assert "statusCode >= 400" in where and "statusCode < 500" in where


def test_clase_desconocida_se_ignora():
    """Un valor invalido no debe traducirse en un filtro arbitrario."""
    where, _binds = construir_filtros({"clase": "cualquier-cosa"})
    assert "statusCode" not in where


def test_filtros_se_combinan_con_and():
    where, binds = construir_filtros({"metodo": "POST", "texto": "orden"})
    assert where.count("AND") >= 1
    assert binds["metodo"] == "POST" and binds["texto"] == "%orden%"


def test_texto_vacio_no_genera_filtro():
    where, binds = construir_filtros({"texto": ""})
    assert "url LIKE" not in where
    assert "texto" not in binds
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_logs_endpoints.py -q
```

Esperado: FAIL con `ImportError: cannot import name 'construir_filtros'`.

- [ ] **Step 3: Implementar**

Agregar al final de `app/routes/logs_productividad.py`:

```python
# Clases de status expuestas en el filtro. El mapa es cerrado a proposito: el
# valor llega del cliente y no puede convertirse en SQL arbitrario.
CLASES_STATUS = {
    "exito": "statusCode >= 200 AND statusCode < 300",
    "redireccion": "statusCode >= 300 AND statusCode < 400",
    "error_cliente": "statusCode >= 400 AND statusCode < 500",
    "error_servidor": "statusCode >= 500",
}


def construir_filtros(filtros: dict) -> tuple[str, dict]:
    """
    Arma el fragmento WHERE del explorador y sus binds.

    Todo valor del cliente viaja como bind, nunca interpolado. La clase de
    status es la unica que se traduce a SQL, y sale de un mapa cerrado.

    Funcion pura, sin I/O.
    """
    condiciones: list[str] = []
    binds: dict = {}

    if filtros.get("metodo"):
        condiciones.append("metodo = :metodo")
        binds["metodo"] = filtros["metodo"]

    if filtros.get("usuario"):
        condiciones.append("nombreUsuario = :usuario")
        binds["usuario"] = filtros["usuario"]

    if filtros.get("texto"):
        condiciones.append("url LIKE :texto")
        binds["texto"] = f"%{filtros['texto']}%"

    if filtros.get("desde"):
        condiciones.append("fechaHoraLog >= :desde")
        binds["desde"] = filtros["desde"]

    if filtros.get("hasta"):
        condiciones.append("fechaHoraLog < DATEADD(DAY, 1, :hasta)")
        binds["hasta"] = filtros["hasta"]

    clase = CLASES_STATUS.get(filtros.get("clase") or "")
    if clase:
        condiciones.append(f"({clase})")

    return (" AND ".join(condiciones), binds)


@router.get("")
def listar_logs(
    metodo: str | None = None,
    usuario: str | None = None,
    texto: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    clase: str | None = None,
    pagina: int = 1,
    por_pagina: int = 50,
    logs_db: Session = Depends(get_logs_db),
):
    """
    Explorador de logs crudos, paginado.

    Devuelve las columnas tal como estan, sin normalizar: el objetivo es
    entender que paso realmente antes de decidir si una ruta cuenta.
    """
    if por_pagina > 200:
        raise HTTPException(
            status_code=400,
            detail="por_pagina no puede superar 200",
        )

    where, binds = construir_filtros({
        "metodo": metodo, "usuario": usuario, "texto": texto,
        "desde": desde, "hasta": hasta, "clase": clase,
    })
    clausula = f"WHERE {where}" if where else ""

    total = logs_db.execute(
        text(f"SELECT COUNT(*) AS n FROM [ObraSocial].[dbo].[LogSistema] {clausula}"),
        binds,
    ).mappings().first()

    filas = logs_db.execute(
        text(f"""
            SELECT fechaHoraLog, nombreUsuario, metodo, url,
                   statusCode, tiempoRespuestaMs, requestId
            FROM [ObraSocial].[dbo].[LogSistema]
            {clausula}
            ORDER BY fechaHoraLog DESC
            OFFSET :salto ROWS FETCH NEXT :toma ROWS ONLY
        """),
        {**binds,
         "salto": max(0, (pagina - 1) * por_pagina),
         "toma": por_pagina},
    ).mappings().all()

    # Se adjunta la ruta normalizada de cada fila para que la pantalla pueda
    # saltar de un log a clasificar su ruta. Se calcula aca y no en el cliente
    # para que exista una sola implementacion de la normalizacion: dos, en dos
    # lenguajes, se desincronizan y el salto llevaria a la ruta equivocada.
    return {
        "logs": [
            {**dict(f), "rutaNormalizada": normalizar_ruta(f["url"])}
            for f in filas
        ],
        "total": total["n"] if total else 0,
        "pagina": pagina,
        "porPagina": por_pagina,
    }
```

- [ ] **Step 4: Correr los tests**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_logs_endpoints.py -q
```

Esperado: `20 passed`.

- [ ] **Step 5: Verificar la consulta paginada contra la base real**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -c "
from app.database.database import SessionLocalObraSocial
from app.routes.logs_productividad import listar_logs
db = SessionLocalObraSocial()
r = listar_logs(metodo='POST', pagina=1, por_pagina=3, logs_db=db)
print('total:', r['total'])
for f in r['logs']: print(' ', f['fechaHoraLog'], f['metodo'], f['url'], f['statusCode'])
db.close()
"
```

Esperado: un total mayor a 40.000 y tres filas POST reales.

- [ ] **Step 6: Correr la suite completa y commitear**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest -q
```

Esperado: `442 passed`.

```bash
git add app/routes/logs_productividad.py tests/test_logs_endpoints.py
git commit -m "feat(logs): explorador de logs crudos con filtros y paginado"
```

---

### Task 6: Migrar el cálculo del score a LogSistema

**Files:**
- Modify: `app/database/score_historico.py`
- Modify: `app/routes/stats.py:37-97` (`calculate_productivity_scores`)
- Modify: `app/routes/logs_productividad.py` (endpoint de recálculo)
- Test: `tests/test_score_logsistema.py`

**Interfaces:**
- Consumes: `normalizar_ruta` (Task 1); `rutas_habilitadas` (Task 2); el `router` (Task 3).
- Produces:
  - `FORMULA_LOGSISTEMA = "eventos_logsistema_v2"` en `score_historico.py`
  - `calculate_productivity_scores(stats_db: Session, habilitadas: set[tuple[str, str]]) -> dict[str, dict]` — **firma nueva**, ahora recibe las rutas habilitadas
  - `agrupar_por_usuario(filas: list[dict], habilitadas: set[tuple[str, str]]) -> dict[str, dict]` — función pura
  - `POST /admin/logs/recalcular`

**Contexto crítico:** `sync_productivity_scores` en `stats.py:335` llama a `calculate_productivity_scores(stats_db)`. Al cambiar la firma hay que actualizar esa llamada para que pase las rutas habilitadas, que se leen de la base de RRHH (`db`, no `stats_db`). El resto de la cadena —vinculación por DNI, horas del reloj, exentos, `registrar_corrida`— **no se toca**.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_score_logsistema.py`:

```python
"""
Tests de la migracion del score a LogSistema.

La fuente anterior, UsuarioAccesoLogs, registra altas y bajas de permisos: no
mide trabajo. Estos tests fijan que solo entre al score lo que un humano
habilito, atribuible y exitoso.
"""

from app.database.score_historico import FORMULA_ACTUAL, FORMULA_LOGSISTEMA
from app.routes.stats import agrupar_por_usuario


HABILITADAS = {("POST", "/afiliado/nueva-consulta")}


def test_suma_solo_las_rutas_habilitadas():
    filas = [
        {"idUsuario": "u1", "metodo": "POST",
         "url": "/afiliado/nueva-consulta", "eventos": 10},
        {"idUsuario": "u1", "metodo": "POST",
         "url": "/usuario/login", "eventos": 99},
    ]
    assert agrupar_por_usuario(filas, HABILITADAS)["u1"]["eventos"] == 10


def test_ruta_no_habilitada_no_crea_usuario():
    """Quien solo tiene actividad no habilitada queda sin medir, que no es
    lo mismo que medido en cero."""
    filas = [{"idUsuario": "u2", "metodo": "POST",
              "url": "/usuario/login", "eventos": 99}]
    assert agrupar_por_usuario(filas, HABILITADAS) == {}


def test_normaliza_antes_de_comparar():
    """La ruta habilitada esta guardada normalizada; la fila viene cruda."""
    filas = [{"idUsuario": "u1", "metodo": "GET",
              "url": "/orden/123", "eventos": 4}]
    resultado = agrupar_por_usuario(filas, {("GET", "/orden/:id")})
    assert resultado["u1"]["eventos"] == 4


def test_suma_varias_rutas_del_mismo_usuario():
    filas = [
        {"idUsuario": "u1", "metodo": "POST",
         "url": "/afiliado/nueva-consulta", "eventos": 10},
        {"idUsuario": "u1", "metodo": "GET",
         "url": "/orden/1", "eventos": 5},
    ]
    habilitadas = HABILITADAS | {("GET", "/orden/:id")}
    assert agrupar_por_usuario(filas, habilitadas)["u1"]["eventos"] == 15


def test_idusuario_se_normaliza_a_minuscula():
    """La vinculacion por DNI produce GUIDs en minuscula; si no coinciden,
    el empleado queda sin score sin que nada lo avise."""
    filas = [{"idUsuario": "U1-ABC", "metodo": "POST",
              "url": "/afiliado/nueva-consulta", "eventos": 3}]
    assert "u1-abc" in agrupar_por_usuario(filas, HABILITADAS)


def test_sin_rutas_habilitadas_no_mide_a_nadie():
    """Antes de que alguien clasifique, nadie tiene score medido: el sistema
    no inventa numeros a partir de una configuracion vacia."""
    filas = [{"idUsuario": "u1", "metodo": "POST",
              "url": "/afiliado/nueva-consulta", "eventos": 10}]
    assert agrupar_por_usuario(filas, set()) == {}


def test_la_formula_nueva_es_distinta_de_la_anterior():
    """Sin esto, el historial viejo y el nuevo se mezclarian en el mismo
    grafico de trayectoria y un cambio de unidad se leeria como caida."""
    assert FORMULA_LOGSISTEMA == "eventos_logsistema_v2"
    assert FORMULA_LOGSISTEMA != FORMULA_ACTUAL
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_score_logsistema.py -q
```

Esperado: FAIL con `ImportError: cannot import name 'FORMULA_LOGSISTEMA'`.

- [ ] **Step 3: Agregar la fórmula nueva**

En `app/database/score_historico.py`, después de la línea 52 (`FORMULA_LEGADA = "eventos_por_sesion_v0"`), agregar:

```python
# Tercera version: la fuente dejo de ser UsuarioAccesoLogs -que registra altas
# y bajas de permisos, no trabajo- y paso a ser LogSistema, filtrado por las
# rutas que un administrador marco como trabajo real. El numerador cambio de
# significado, asi que las corridas anteriores no son comparables con estas.
FORMULA_LOGSISTEMA = "eventos_logsistema_v2"
```

- [ ] **Step 4: Reemplazar la consulta del score**

En `app/routes/stats.py`, reemplazar íntegramente `calculate_productivity_scores` (líneas 37 a 97) por:

```python
# Cuanto tiene que pasar entre dos requests para contarlos como dos acciones.
# Sin esto, un formulario que dispara cinco llamadas al guardar valdria cinco
# veces mas que uno que dispara una.
COOLDOWN_SEG = 3

ACTIVIDAD_SQL = text("""
    DECLARE @cooldown_sec INT = :cooldown;
    ;WITH LogsFiltrados AS (
        SELECT l.idUsuario, l.metodo, l.url, l.fechaHoraLog AS creado
        FROM [ObraSocial].[dbo].[LogSistema] l
        WHERE l.fechaHoraLog >= DATEADD(MONTH, -:meses, GETDATE())
          AND l.idUsuario IS NOT NULL
          AND l.statusCode >= 200 AND l.statusCode < 300
    ),
    Ordenados AS (
        SELECT *,
               LAG(creado) OVER (PARTITION BY idUsuario ORDER BY creado)
                   AS prev_time
        FROM LogsFiltrados
    ),
    SinSpam AS (
        SELECT *
        FROM Ordenados
        WHERE prev_time IS NULL
           OR DATEDIFF(SECOND, prev_time, creado) >= @cooldown_sec
    )
    SELECT idUsuario, metodo, url, COUNT(*) AS eventos
    FROM SinSpam
    GROUP BY idUsuario, metodo, url
""")


def agrupar_por_usuario(
    filas: list[dict],
    habilitadas: set[tuple[str, str]],
) -> dict[str, dict]:
    """
    Suma los eventos de cada usuario, contando solo las rutas habilitadas.

    El filtro se aplica aca y no en SQL porque la configuracion vive en la
    base de RRHH y la actividad en la de ObraSocial: no se pueden unir en una
    sola consulta. El volumen lo permite holgadamente.

    Un usuario sin ninguna ruta habilitada no aparece en el resultado, y eso
    se traduce mas adelante en score None: no se lo pudo medir, que no es lo
    mismo que haber trabajado cero.

    Funcion pura, sin I/O.
    """
    por_usuario: dict[str, dict] = {}

    for fila in filas:
        clave = (fila["metodo"], normalizar_ruta(fila["url"]))
        if clave not in habilitadas:
            continue
        # El resto de la cadena compara contra GUIDs en minuscula. Si no se
        # normaliza, el empleado queda sin score y nada lo avisa.
        usuario = str(fila["idUsuario"]).lower()
        actual = por_usuario.setdefault(usuario, {"eventos": 0})
        actual["eventos"] += fila["eventos"]

    return por_usuario


def calculate_productivity_scores(
    stats_db: Session,
    habilitadas: set[tuple[str, str]],
) -> dict[str, dict]:
    """
    Eventos de trabajo por usuario de ObraSocial, en la ventana del calculo.

    Antes leia UsuarioAccesoLogs, que registra altas y bajas de permisos: el
    numero que salia de ahi no media el trabajo de nadie. Ahora lee LogSistema,
    descartando lo que no es atribuible -el 39% de las filas no tiene usuario-
    y lo que no salio bien: contar un 401 en loop como trabajo repetiria el
    problema que este cambio corrige.

    'sesiones' queda en None a proposito. La formula es eventos sobre horas
    efectivas del reloj y no usa sesiones; guardarlas seria un dato inventado.
    """
    filas = stats_db.execute(
        ACTIVIDAD_SQL, {"cooldown": COOLDOWN_SEG, "meses": VENTANA_MESES}
    ).mappings().all()

    agrupado = agrupar_por_usuario([dict(f) for f in filas], habilitadas)
    return {
        usuario: {"score": None, "sesiones": None, "eventos": d["eventos"]}
        for usuario, d in agrupado.items()
    }
```

Agregar los imports necesarios al encabezado de `stats.py`, junto a los existentes:

```python
from app.database.rutas_productividad import rutas_habilitadas
from app.services.normalizar_ruta import normalizar_ruta
```

Y agregar `FORMULA_LOGSISTEMA` al import ya existente desde `app.database.score_historico`.

- [ ] **Step 5: Actualizar la llamada y la fórmula registrada**

En `app/routes/stats.py`, dentro de `sync_productivity_scores`, reemplazar la línea 345:

```python
detalle_por_usuario = calculate_productivity_scores(stats_db)
```

por:

```python
# Las rutas habilitadas viven en la base de RRHH; la actividad, en la de
# ObraSocial. Por eso se leen de db y se pasan explicitamente.
habilitadas = rutas_habilitadas(db)
detalle_por_usuario = calculate_productivity_scores(stats_db, habilitadas)
```

Y borrar la línea 346, que ya no aplica porque `score` ahora siempre viene en None:

```python
scores_by_user = {uid: d["score"] for uid, d in detalle_por_usuario.items()}
```

En la llamada a `registrar_corrida` (línea 396), cambiar:

```python
"formula": FORMULA_ACTUAL,
```

por:

```python
"formula": FORMULA_LOGSISTEMA,
```

- [ ] **Step 6: Verificar que la fuente vieja no quedó referenciada**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && grep -n "UsuarioAccesoLogs\|scores_by_user" app/routes/stats.py
```

Esperado: **sin salida**. Si aparece `UsuarioAccesoLogs`, la migración quedó a medias. Si aparece `scores_by_user`, el paso anterior no borró la línea 346.

`asignar_scores` (línea 160) **no se toca**: ya era código muerto antes de este trabajo — `sync_productivity_scores` calcula con `score_por_hora`, no con él — y tiene tests propios en `tests/test_score_vinculacion.py`. Limpiarlo es una tarea aparte, fuera del alcance de este plan.

- [ ] **Step 7: Agregar el endpoint de recálculo**

En `app/routes/logs_productividad.py`, agregar al final:

```python
@router.post("/recalcular")
def recalcular_scores(
    db: Session = Depends(get_db),
    logs_db: Session = Depends(get_logs_db),
):
    """
    Dispara a mano la misma corrida que hace el scheduler cada dia.

    Existe porque tildar rutas no tiene efecto visible hasta la corrida
    siguiente, y esa demora se lee como que la pantalla no funciona. El
    recalculo alcanza los 12 meses de la ventana, no solo lo que viene: la
    clasificacion describe que es trabajo, y eso no depende de cuando se tildo.
    """
    from app.routes.stats import sync_productivity_scores

    try:
        sync_productivity_scores(db, logs_db)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo recalcular: {e}",
        )
    return {"success": True}
```

El import va adentro de la función a propósito: `stats.py` importa de este módulo la configuración de rutas, y a nivel de módulo sería un ciclo.

- [ ] **Step 8: Correr los tests**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest tests/test_score_logsistema.py -q
```

Esperado: `7 passed`.

- [ ] **Step 9: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -m pytest -q
```

Esperado: `449 passed`.

Ningún test existente llama a `calculate_productivity_scores` — su única llamada está en `stats.py:345`, que este mismo task actualiza — así que el cambio de firma no debería romper nada. Si algo falla acá, es una regresión real y hay que investigarla, no ajustar el test para que pase.

- [ ] **Step 10: Verificar la consulta contra la base real**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && ./venv/Scripts/python.exe -c "
from app.database.database import SessionLocalObraSocial
from app.routes.stats import ACTIVIDAD_SQL, COOLDOWN_SEG
db = SessionLocalObraSocial()
filas = db.execute(ACTIVIDAD_SQL, {'cooldown': COOLDOWN_SEG, 'meses': 12}).mappings().all()
print('filas:', len(filas))
print('eventos totales:', sum(f['eventos'] for f in filas))
db.close()
"
```

Esperado: varios miles de filas y un total menor a 28.913 (el cooldown descarta parte).

- [ ] **Step 11: Commit**

```bash
git add app/routes/stats.py app/database/score_historico.py app/routes/logs_productividad.py tests/
git commit -m "feat(score): calcular productividad sobre LogSistema filtrado por rutas"
```

---

### Task 7: Frontend — tab Productividad con la vista de rutas

**Files:**
- Create: `src/app/Componentes/Admin/RutasProductividad.tsx`
- Create: `src/app/Componentes/Admin/ProductividadTab.tsx`
- Modify: `src/app/Interfas/Interfaces.ts`
- Modify: `src/app/screens/Admin/Screen.tsx:322-332` y `:370-372`

Rutas relativas a `C:\Users\Emiliano\Documents\RRHH`.

**Interfaces:**
- Consumes: `GET /admin/logs/rutas`, `PUT /admin/logs/rutas`, `POST /admin/logs/recalcular` (Tasks 3, 4, 6).
- Produces: `<ProductividadTab />`, montado desde `Screen.tsx`.

**Contexto:** La pantalla de Administración ya tiene tabs y usa `admin.gestionar`. Se suma uno, sin tocar el sidebar.

- [ ] **Step 1: Agregar los tipos**

En `src/app/Interfas/Interfaces.ts`, agregar al final:

```typescript
export type EstadoRuta = "cuenta" | "no_cuenta" | "pendiente";

export interface RutaProductividad {
  metodo: string;
  ruta: string;
  eventos: number;
  usuarios: number;
  ultimaVez: string | null;
  estado: EstadoRuta;
}

export interface LogSistemaFila {
  fechaHoraLog: string;
  nombreUsuario: string | null;
  metodo: string;
  url: string;
  rutaNormalizada: string;
  statusCode: number;
  tiempoRespuestaMs: number | null;
  requestId: string | null;
}
```

- [ ] **Step 2: Crear la vista de rutas**

Crear `src/app/Componentes/Admin/RutasProductividad.tsx`:

```tsx
"use client";

// Clasificacion de que rutas del sistema de gestion cuentan como trabajo.
//
// El orden es por volumen descendente y no alfabetico a proposito: las 25
// rutas mas usadas concentran el 79% de la actividad, asi que tildando de
// arriba hacia abajo se resuelve casi todo en una pasada.

import React from "react";
import { AlertTriangle, RefreshCw, Save, Search } from "lucide-react";
import { apiClient } from "@/app/util/apiClient";
import type { EstadoRuta, RutaProductividad } from "@/app/Interfas/Interfaces";

type Filtro = "todas" | EstadoRuta;

// `resaltar` llega cuando se viene desde el explorador de logs con una ruta
// concreta que se quiere clasificar. Se traduce a la busqueda de texto en vez
// de a un scroll: dejar visible solo esa fila evita tener que buscarla a ojo
// en una tabla de 1.830.
export function RutasProductividad({ resaltar }: { resaltar?: string }) {
  const [rutas, setRutas] = React.useState<RutaProductividad[]>([]);
  const [cambios, setCambios] = React.useState<Map<string, boolean>>(new Map());
  const [filtro, setFiltro] = React.useState<Filtro>("todas");
  const [busqueda, setBusqueda] = React.useState(resaltar ?? "");
  const [cargando, setCargando] = React.useState(true);
  const [guardando, setGuardando] = React.useState(false);
  const [recalculando, setRecalculando] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [sinActividad, setSinActividad] = React.useState(false);

  const clave = (r: { metodo: string; ruta: string }) => `${r.metodo} ${r.ruta}`;

  const traer = React.useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const r = await apiClient.get<{
        rutas: RutaProductividad[];
        actividadDisponible: boolean;
      }>("/admin/logs/rutas");
      setRutas(r.rutas ?? []);
      setSinActividad(!r.actividadDisponible);
      setCambios(new Map());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setCargando(false);
    }
  }, []);

  React.useEffect(() => {
    void traer();
  }, [traer]);

  // Al volver desde Logs con otra ruta, la busqueda tiene que seguirla. Sin
  // esto el salto solo funcionaria la primera vez.
  React.useEffect(() => {
    if (resaltar) {
      setBusqueda(resaltar);
      setFiltro("todas");
    }
  }, [resaltar]);

  const tildada = (r: RutaProductividad): boolean => {
    const pendienteDeGuardar = cambios.get(clave(r));
    return pendienteDeGuardar ?? r.estado === "cuenta";
  };

  const alternar = (r: RutaProductividad) => {
    const siguiente = new Map(cambios);
    siguiente.set(clave(r), !tildada(r));
    setCambios(siguiente);
  };

  const guardar = async () => {
    if (cambios.size === 0) return;
    setGuardando(true);
    try {
      await apiClient.put("/admin/logs/rutas", {
        rutas: rutas
          .filter((r) => cambios.has(clave(r)))
          .map((r) => ({
            metodo: r.metodo,
            ruta: r.ruta,
            cuenta: cambios.get(clave(r)),
          })),
      });
      await traer();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  const recalcular = async () => {
    setRecalculando(true);
    try {
      await apiClient.post("/admin/logs/recalcular", {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo recalcular");
    } finally {
      setRecalculando(false);
    }
  };

  const pendientes = rutas.filter((r) => r.estado === "pendiente");
  const visibles = rutas.filter(
    (r) =>
      (filtro === "todas" || r.estado === filtro) &&
      (busqueda === "" ||
        r.ruta.toLowerCase().includes(busqueda.toLowerCase()))
  );

  if (cargando) {
    return <p className="py-8 text-center text-muted-foreground">Cargando rutas…</p>;
  }

  return (
    <div>
      {sinActividad && (
        <div className="mb-4 rounded-xl border-l-4 border-warning bg-warning-soft p-4">
          <p className="text-sm text-warning-soft-foreground">
            No se pudo leer la actividad del sistema de gestión. Se muestra la
            configuración guardada; podés seguir clasificando.
          </p>
        </div>
      )}

      {pendientes.length > 0 && (
        <div className="mb-4 flex items-center gap-3 rounded-xl bg-info-soft p-4">
          <AlertTriangle className="shrink-0 text-info" size={18} />
          <p className="text-sm text-info-soft-foreground">
            Hay <strong>{pendientes.length}</strong> rutas sin clasificar. No
            suman al puntaje hasta que las revises.{" "}
            <button
              type="button"
              onClick={() => setFiltro("pendiente")}
              className="underline font-medium"
            >
              Ver sólo esas
            </button>
          </p>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[14rem] flex-1">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            size={16}
          />
          <input
            type="text"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar ruta…"
            className="w-full rounded-lg border border-border bg-card py-2 pl-9 pr-3 text-foreground"
          />
        </div>

        {(["todas", "pendiente", "cuenta", "no_cuenta"] as Filtro[]).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFiltro(f)}
            className={`rounded-lg px-3 py-1.5 text-sm ${
              filtro === f
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground"
            }`}
          >
            {{
              todas: "Todas",
              pendiente: "Sin clasificar",
              cuenta: "Cuentan",
              no_cuenta: "No cuentan",
            }[f]}
          </button>
        ))}

        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={guardar}
            disabled={cambios.size === 0 || guardando}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
          >
            <Save size={16} />
            {guardando ? "Guardando…" : `Guardar (${cambios.size})`}
          </button>
          <button
            type="button"
            onClick={recalcular}
            disabled={recalculando}
            className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-foreground disabled:opacity-50"
          >
            <RefreshCw size={16} className={recalculando ? "animate-spin" : ""} />
            Recalcular puntajes
          </button>
        </div>
      </div>

      <p className="mb-3 text-sm text-muted-foreground">
        Tildar una ruta recalcula los últimos 12 meses, no sólo lo que viene.
      </p>

      {error && <p className="mb-3 text-sm text-error">{error}</p>}

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-border bg-muted text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              <th className="px-4 py-3">Cuenta</th>
              <th className="px-4 py-3">Método</th>
              <th className="px-4 py-3">Ruta</th>
              <th className="px-4 py-3 text-right">Eventos</th>
              <th className="px-4 py-3 text-right">Usuarios</th>
              <th className="px-4 py-3">Última vez</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {visibles.map((r) => (
              <tr key={clave(r)} className="hover:bg-muted/50">
                <td className="px-4 py-2">
                  <input
                    type="checkbox"
                    checked={tildada(r)}
                    onChange={() => alternar(r)}
                    aria-label={`Contar ${r.metodo} ${r.ruta}`}
                    className="h-4 w-4 accent-[var(--primary)]"
                  />
                </td>
                <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                  {r.metodo}
                </td>
                <td className="px-4 py-2 font-mono text-sm text-foreground">
                  {r.ruta}
                  {r.estado === "pendiente" && (
                    <span className="ml-2 rounded bg-info-soft px-1.5 py-0.5 text-[10px] text-info-soft-foreground">
                      sin clasificar
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-foreground">
                  {r.eventos.toLocaleString("es-AR")}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                  {r.usuarios}
                </td>
                <td className="px-4 py-2 text-sm text-muted-foreground">
                  {r.ultimaVez ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {visibles.length === 0 && (
        <p className="py-8 text-center text-muted-foreground">
          No hay rutas con ese filtro.
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Crear el contenedor del tab**

Crear `src/app/Componentes/Admin/ProductividadTab.tsx`:

```tsx
"use client";

// Contenedor del tab Productividad, con las dos vistas.
//
// Clasificar es la tarea principal, asi que Rutas es la vista por defecto.
// Logs existe para poder mirar que es realmente una ruta antes de decidir.

import React from "react";
import { RutasProductividad } from "./RutasProductividad";
import { LogsExplorer } from "./LogsExplorer";

type Vista = "rutas" | "logs";

export function ProductividadTab() {
  const [vista, setVista] = React.useState<Vista>("rutas");
  // Ruta que quedo pendiente de clasificar al saltar desde el explorador. El
  // estado vive aca porque es lo unico que las dos vistas comparten.
  const [rutaASaltar, setRutaASaltar] = React.useState<string | undefined>();

  const saltarAClasificar = (ruta: string) => {
    setRutaASaltar(ruta);
    setVista("rutas");
  };

  const cambiarVista = (v: Vista) => {
    // Volver a Rutas por el boton, y no por el salto, muestra la tabla
    // completa: si quedara filtrada por la ruta anterior pareceria vacia.
    if (v === "rutas") setRutaASaltar(undefined);
    setVista(v);
  };

  return (
    <div>
      <div className="mb-4 flex gap-2">
        {(["rutas", "logs"] as Vista[]).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => cambiarVista(v)}
            className={`rounded-lg px-4 py-2 text-sm font-medium ${
              vista === v
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground"
            }`}
          >
            {v === "rutas" ? "Rutas" : "Logs"}
          </button>
        ))}
      </div>

      {vista === "rutas" ? (
        <RutasProductividad resaltar={rutaASaltar} />
      ) : (
        <LogsExplorer onClasificar={saltarAClasificar} />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Montar el tab**

En `src/app/screens/Admin/Screen.tsx`, agregar el import junto a los demás componentes:

```tsx
import { ProductividadTab } from '@/app/Componentes/Admin/ProductividadTab';
```

Agregar el botón después de `<TabButton id="profiles" title="Perfiles de Usuario" />`:

```tsx
<TabButton id="productividad" title="Productividad" />
```

Y el render después de `{activeTab === 'profiles' && <ProfileSettings />}`:

```tsx
{activeTab === 'productividad' && <ProductividadTab />}
```

- [ ] **Step 5: Verificar tipos**

`LogsExplorer` todavía no existe, así que este paso va a fallar en ese import. Es esperado: la Task 8 lo crea. Para verificar el resto sin ruido, correr:

```bash
cd /c/Users/Emiliano/Documents/RRHH && npx tsc --noEmit 2>&1 | grep -v "LogsExplorer" | grep -c "error TS"
```

Esperado: `27`, el baseline. Cualquier número mayor son errores introducidos por esta tarea.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/Emiliano/Documents/RRHH
git add src/app/Componentes/Admin/RutasProductividad.tsx src/app/Componentes/Admin/ProductividadTab.tsx src/app/Interfas/Interfaces.ts src/app/screens/Admin/Screen.tsx
git commit -m "feat(admin): tab Productividad con clasificacion de rutas"
```

---

### Task 8: Frontend — explorador de logs

**Files:**
- Create: `src/app/Componentes/Admin/LogsExplorer.tsx`

Ruta relativa a `C:\Users\Emiliano\Documents\RRHH`.

**Interfaces:**
- Consumes: `GET /admin/logs` (Task 5); el tipo `LogSistemaFila` (Task 7).
- Produces: `<LogsExplorer />`, consumido por `ProductividadTab` (Task 7).

**Contexto:** Cierra el import pendiente de la Task 7. Es la tabla cruda que permite entender qué es una ruta antes de tildarla.

- [ ] **Step 1: Implementar**

Crear `src/app/Componentes/Admin/LogsExplorer.tsx`:

```tsx
"use client";

// Explorador de los logs crudos del sistema de gestion.
//
// Muestra las columnas tal como vienen, sin normalizar: el objetivo es
// entender que paso realmente antes de decidir si una ruta cuenta como
// trabajo. Normalizarlas aca escondria justamente lo que se viene a mirar.

import React from "react";
import { Search } from "lucide-react";
import { apiClient } from "@/app/util/apiClient";
import type { LogSistemaFila } from "@/app/Interfas/Interfaces";

const CLASES = [
  { valor: "", etiqueta: "Todos" },
  { valor: "exito", etiqueta: "Éxito (2xx)" },
  { valor: "redireccion", etiqueta: "Redirección (3xx)" },
  { valor: "error_cliente", etiqueta: "Error cliente (4xx)" },
  { valor: "error_servidor", etiqueta: "Error servidor (5xx)" },
];

const POR_PAGINA = 50;

// `onClasificar` recibe la ruta ya normalizada por el backend. Se usa la del
// backend y no una calculada aca para que exista una sola implementacion de
// la normalizacion: dos, en dos lenguajes, se desincronizan.
export function LogsExplorer({
  onClasificar,
}: {
  onClasificar?: (ruta: string) => void;
}) {
  const [logs, setLogs] = React.useState<LogSistemaFila[]>([]);
  const [total, setTotal] = React.useState(0);
  const [pagina, setPagina] = React.useState(1);
  const [texto, setTexto] = React.useState("");
  const [metodo, setMetodo] = React.useState("");
  const [clase, setClase] = React.useState("");
  const [cargando, setCargando] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const traer = React.useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        pagina: String(pagina),
        por_pagina: String(POR_PAGINA),
      });
      if (texto) params.set("texto", texto);
      if (metodo) params.set("metodo", metodo);
      if (clase) params.set("clase", clase);

      const r = await apiClient.get<{ logs: LogSistemaFila[]; total: number }>(
        `/admin/logs?${params.toString()}`
      );
      setLogs(r.logs ?? []);
      setTotal(r.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setCargando(false);
    }
  }, [pagina, texto, metodo, clase]);

  React.useEffect(() => {
    void traer();
  }, [traer]);

  // Cualquier cambio de filtro invalida la pagina actual: quedarse en la 7 de
  // un resultado que ahora tiene 2 mostraria una tabla vacia sin explicacion.
  const cambiarFiltro = (accion: () => void) => {
    accion();
    setPagina(1);
  };

  const colorStatus = (s: number) =>
    s < 300 ? "text-success" : s < 400 ? "text-muted-foreground" : "text-error";

  const paginas = Math.max(1, Math.ceil(total / POR_PAGINA));

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[14rem]">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            size={16}
          />
          <input
            type="text"
            value={texto}
            onChange={(e) => cambiarFiltro(() => setTexto(e.target.value))}
            placeholder="Buscar en la URL…"
            className="w-full rounded-lg border border-border bg-card py-2 pl-9 pr-3 text-foreground"
          />
        </div>

        <select
          value={metodo}
          onChange={(e) => cambiarFiltro(() => setMetodo(e.target.value))}
          className="rounded-lg border border-border bg-card px-3 py-2 text-foreground"
        >
          <option value="">Todos los métodos</option>
          {["GET", "POST", "PUT", "DELETE"].map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>

        <select
          value={clase}
          onChange={(e) => cambiarFiltro(() => setClase(e.target.value))}
          className="rounded-lg border border-border bg-card px-3 py-2 text-foreground"
        >
          {CLASES.map((c) => (
            <option key={c.valor} value={c.valor}>{c.etiqueta}</option>
          ))}
        </select>
      </div>

      {error && <p className="mb-3 text-sm text-error">{error}</p>}

      {cargando ? (
        <p className="py-8 text-center text-muted-foreground">Cargando logs…</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-border bg-muted text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                <th className="px-4 py-3">Fecha</th>
                <th className="px-4 py-3">Usuario</th>
                <th className="px-4 py-3">Método</th>
                <th className="px-4 py-3">URL</th>
                <th className="px-4 py-3 text-right">Status</th>
                <th className="px-4 py-3 text-right">ms</th>
                <th className="px-4 py-3">Ruta</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {logs.map((l, i) => (
                <tr key={`${l.requestId ?? i}-${i}`} className="hover:bg-muted/50">
                  <td className="px-4 py-2 text-sm text-muted-foreground">
                    {new Date(l.fechaHoraLog).toLocaleString("es-AR")}
                  </td>
                  <td className="px-4 py-2 text-sm text-foreground">
                    {l.nombreUsuario ?? "—"}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                    {l.metodo}
                  </td>
                  <td className="px-4 py-2 font-mono text-sm text-foreground">
                    {l.url}
                  </td>
                  <td className={`px-4 py-2 text-right tabular-nums ${colorStatus(l.statusCode)}`}>
                    {l.statusCode}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                    {l.tiempoRespuestaMs ?? "—"}
                  </td>
                  <td className="px-4 py-2">
                    {onClasificar ? (
                      <button
                        type="button"
                        onClick={() => onClasificar(l.rutaNormalizada)}
                        className="font-mono text-xs text-primary underline"
                        title="Clasificar esta ruta"
                      >
                        {l.rutaNormalizada}
                      </button>
                    ) : (
                      <span className="font-mono text-xs text-muted-foreground">
                        {l.rutaNormalizada}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {logs.length === 0 && !cargando && (
        <p className="py-8 text-center text-muted-foreground">
          No hay logs con esos filtros.
        </p>
      )}

      <div className="mt-4 flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {total.toLocaleString("es-AR")} registros
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPagina((p) => Math.max(1, p - 1))}
            disabled={pagina <= 1}
            className="rounded-lg border border-border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            Anterior
          </button>
          <span className="text-sm text-muted-foreground">
            {pagina} de {paginas}
          </span>
          <button
            type="button"
            onClick={() => setPagina((p) => Math.min(paginas, p + 1))}
            disabled={pagina >= paginas}
            className="rounded-lg border border-border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            Siguiente
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos, ahora sin exclusiones**

```bash
cd /c/Users/Emiliano/Documents/RRHH && npx tsc --noEmit 2>&1 | grep -c "error TS"
```

Esperado: `27`, el baseline exacto.

- [ ] **Step 3: Verificar que no hay errores en los archivos nuevos**

```bash
cd /c/Users/Emiliano/Documents/RRHH && npx tsc --noEmit 2>&1 | grep -E "LogsExplorer|RutasProductividad|ProductividadTab"
```

Esperado: sin salida.

- [ ] **Step 4: Commit**

```bash
cd /c/Users/Emiliano/Documents/RRHH
git add src/app/Componentes/Admin/LogsExplorer.tsx
git commit -m "feat(admin): explorador de logs crudos con filtros y paginado"
```

---

## Verificación final

Después de la Task 8, con el backend corriendo y sesión de administrador:

1. Entrar a Administración → Productividad. La vista Rutas carga con el aviso de rutas sin clasificar.
2. Tildar `POST /afiliado/nueva-consulta` y guardar. El contador de pendientes baja en uno.
3. Presionar "Recalcular puntajes" y confirmar que responde sin error.
4. Ir a Estadísticas → Indicadores por persona y verificar que los puntajes cambiaron.
5. Volver a Productividad → Logs, filtrar por método POST y por error de cliente, y confirmar que la tabla responde.
6. En la columna Ruta de un log, hacer clic. Debe llevar a la vista Rutas con esa ruta ya filtrada y lista para tildar.

**Paso operativo, no de desarrollo:** al 2026-09-02 no hay ningún departamento marcado como exento y la tabla `Office` está vacía. Antes de dar por buena la migración en producción hay que marcar en el organigrama las áreas cuyo trabajo no pasa por el sistema de gestión. Si no, esas personas medirían cerca de cero.
