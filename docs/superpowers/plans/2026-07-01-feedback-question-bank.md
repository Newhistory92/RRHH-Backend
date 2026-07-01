# Banco de preguntas de Feedback 360° — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear el modelo de datos (`Pregunta`, `RespuestaFeedback`), sembrar las 30 preguntas base + 8 de ambiente laboral general, y exponer un endpoint de solo lectura para listarlas.

**Architecture:** Un módulo `app/database/feedback_preguntas.py` con `ensure_table()` (crea ambas tablas, idempotente) + seed no destructivo, siguiendo el mismo patrón que `app/database/feriados.py` y `app/database/academic_title_mapping.py`. Un nuevo endpoint `GET /feedback/preguntas` en el router existente `app/routes/feedback.py`, que llama a `ensure_table()` de forma lazy (mismo patrón que usan los endpoints de feriados) y lee de la tabla.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc).

## Global Constraints

- Las tablas `Feedback`, `Respuesta`, `FeedbackEvaluacion` actuales NO se tocan ni se leen/escriben desde este código nuevo — quedan intactas y sin usar.
- `app/main.py` NO se modifica (el router `feedback` ya está registrado — `app/main.py:26` — y tiene WIP no relacionado del dueño del repo que no debe tocarse).
- El seed solo corre si la tabla `Pregunta` está vacía (no duplica filas en cada arranque ni en cada request).
- La escala estándar es `["Siempre","Casi siempre","Algunas veces","Rara vez","Nunca"]` (valores 5,4,3,2,1). Las preguntas 27 y 28 (categoría Confianza) usan sus propias 5 etiquetas.
- Numeración de preguntas: 1–4, 6–31 (30 preguntas base, sin la #5 — nunca especificada por el negocio) + 8 preguntas de ambiente general sin número.

---

### Task 1: Tabla, seed y funciones de acceso a datos

**Files:**
- Create: `app/database/feedback_preguntas.py`
- Test: verificación manual (no hay test suite en el repo backend)

**Interfaces:**
- Produces: `ensure_table(db: Session) -> None`, `get_preguntas(db: Session, solo_liderazgo: bool | None = None, es_ambiente_general: bool | None = None) -> list[dict]` — cada dict tiene las claves `id, texto, categoria, tipo, opcionesEscala, soloLiderazgo, esAmbienteGeneral`. `opcionesEscala` se devuelve ya parseado como `list[str] | None` (no como el string JSON crudo).

- [ ] **Step 1: Crear el archivo con el CREATE TABLE de ambas tablas**

```python
"""
Banco de preguntas de Feedback 360 y modelo de respuestas individuales.

Reemplaza el modelo agregado anterior (Feedback/Respuesta/FeedbackEvaluacion,
que siguen existiendo en la base pero sin uso desde este modulo) por un
banco de preguntas fijo mas una tabla de respuestas individuales, para
soportar escala 1-5, preguntas de texto libre, y vinculo directo a
oficina/departamento/periodo por cada respuesta.
"""

import json
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


CREATE_TABLES_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'Pregunta' AND xtype = 'U'
)
BEGIN
    CREATE TABLE Pregunta (
        id                INT IDENTITY(1,1) PRIMARY KEY,
        texto             NVARCHAR(500)  NOT NULL,
        categoria         NVARCHAR(100)  NOT NULL,
        tipo              NVARCHAR(20)   NOT NULL,
        opcionesEscala    NVARCHAR(500)  NULL,
        soloLiderazgo     BIT            NOT NULL DEFAULT 0,
        esAmbienteGeneral BIT            NOT NULL DEFAULT 0,
        activo            BIT            NOT NULL DEFAULT 1,
        createdAt         DATETIME2      NOT NULL
    );
END

IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'RespuestaFeedback' AND xtype = 'U'
)
BEGIN
    CREATE TABLE RespuestaFeedback (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        preguntaId          INT            NOT NULL REFERENCES Pregunta(id),
        evaluadorEmployeeId INT            NOT NULL,
        evaluadoEmployeeId  INT            NULL,
        officeId            INT            NULL,
        departmentId        INT            NULL,
        periodo             DATE           NOT NULL,
        valorEscala         INT            NULL,
        textoLibre          NVARCHAR(MAX)  NULL,
        createdAt           DATETIME2      NOT NULL
    );
    CREATE INDEX IX_RespuestaFeedback_periodo ON RespuestaFeedback (periodo);
    CREATE INDEX IX_RespuestaFeedback_evaluado ON RespuestaFeedback (evaluadoEmployeeId);
END
"""
```

- [ ] **Step 2: Agregar la lista de las 30 preguntas base + 8 de ambiente general**

Agregar debajo del `CREATE_TABLES_SQL`, en el mismo archivo. Cada tupla es `(numero, texto, categoria, tipo, opcionesEscala, soloLiderazgo, esAmbienteGeneral)`. `opcionesEscala` es `None` para usar la escala estándar en el momento del seed (se resuelve en el Step 3), o una lista explícita para las excepciones (Confianza), o `None` para texto libre (el `tipo` ya lo indica).

```python
ESCALA_ESTANDAR = ["Siempre", "Casi siempre", "Algunas veces", "Rara vez", "Nunca"]

# (texto, categoria, tipo, opcionesEscala | None, soloLiderazgo, esAmbienteGeneral)
PREGUNTAS_BASE = [
    # 1. Respeto y convivencia
    ("¿La persona trata a sus compañeros con respeto?", "Respeto y convivencia", "escala", None, False, False),
    ("¿Mantiene un trato cordial durante la jornada laboral?", "Respeto y convivencia", "escala", None, False, False),
    ("¿Has presenciado conductas inapropiadas por parte de esta persona?", "Respeto y convivencia", "escala", None, False, False),
    ("¿Comparte información importante con el equipo?", "Respeto y convivencia", "escala", None, False, False),
    ("¿Genera conflictos innecesarios?", "Respeto y convivencia", "escala", None, False, False),
    # 3. Comunicación
    ("¿Escucha las opiniones de los demás?", "Comunicación", "escala", None, False, False),
    ("¿Expresa sus ideas de forma respetuosa?", "Comunicación", "escala", None, False, False),
    ("¿Acepta críticas constructivas?", "Comunicación", "escala", None, False, False),
    # 4. Responsabilidad
    ("¿Cumple con sus tareas en tiempo y forma?", "Responsabilidad", "escala", None, False, False),
    ("¿Es confiable cuando se le asigna una tarea?", "Responsabilidad", "escala", None, False, False),
    ("¿Su trabajo genera retrabajos para otros?", "Responsabilidad", "escala", None, False, False),
    # 5. Profesionalismo
    ("¿Respeta horarios y normas internas?", "Profesionalismo", "escala", None, False, False),
    ("¿Mantiene una actitud profesional?", "Profesionalismo", "escala", None, False, False),
    # 6. Liderazgo (solo para jefes)
    ("¿Brinda instrucciones claras?", "Liderazgo", "escala", None, True, False),
    ("¿Escucha las inquietudes del equipo?", "Liderazgo", "escala", None, True, False),
    ("¿Distribuye el trabajo de manera justa?", "Liderazgo", "escala", None, True, False),
    ("¿Reconoce el buen desempeño?", "Liderazgo", "escala", None, True, False),
    ("¿Resuelve conflictos de manera adecuada?", "Liderazgo", "escala", None, True, False),
    # 7. Riesgos laborales
    ("¿Alguna persona del equipo genera un ambiente tenso?", "Riesgos laborales", "escala", None, False, False),
    ("¿Te sentís cómodo trabajando con esta persona?", "Riesgos laborales", "escala", None, False, False),
    ("¿Evitás interactuar con esta persona cuando es posible?", "Riesgos laborales", "escala", None, False, False),
    ("¿Considerás que esta persona afecta negativamente al equipo?", "Riesgos laborales", "escala", None, False, False),
    # 8. Conductas de riesgo
    ("¿Has observado faltas de respeto hacia compañeros?", "Conductas de riesgo", "escala", None, False, False),
    ("¿Has observado conductas intimidantes o agresivas?", "Conductas de riesgo", "escala", None, False, False),
    ("¿Creés que esta persona discrimina o hace comentarios ofensivos?", "Conductas de riesgo", "escala", None, False, False),
    # 9. Confianza (escalas propias)
    ("¿Confiarías en esta persona para trabajar en una tarea importante?", "Confianza", "escala",
        ["Totalmente", "Sí", "Parcialmente", "Poco", "No"], False, False),
    ("¿Volverías a elegir trabajar con esta persona?", "Confianza", "escala",
        ["Sí, sin dudas", "Sí", "Me es indiferente", "Preferiría que no", "Definitivamente no"], False, False),
    # 10. Preguntas abiertas
    ("¿Qué fortalezas destacás de esta persona?", "Preguntas abiertas", "texto_libre", None, False, False),
    ("¿Qué aspecto debería mejorar?", "Preguntas abiertas", "texto_libre", None, False, False),
    ("¿Hay algo que Recursos Humanos o la dirección debería conocer?", "Preguntas abiertas", "texto_libre", None, False, False),
]

PREGUNTAS_AMBIENTE_GENERAL = [
    ("¿Te sentís valorado en tu trabajo?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Existe favoritismo?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Te sentís escuchado?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Te sentís cómodo expresando desacuerdos?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Existe colaboración entre áreas?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Te sentís sobrecargado de trabajo?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Has pensado en renunciar por el ambiente laboral?", "Ambiente laboral general", "escala", None, False, True),
    ("¿Recomendarías esta oficina como lugar para trabajar?", "Ambiente laboral general", "escala", None, False, True),
]
```

- [ ] **Step 3: Agregar `ensure_table()` con el seed no destructivo**

```python
def ensure_table(db: Session) -> None:
    """Crea Pregunta y RespuestaFeedback si no existen, y siembra el
    banco de preguntas solo si Pregunta esta vacia (no duplica en cada
    llamada ni pisa preguntas que RRHH haya desactivado a mano)."""
    db.execute(text(CREATE_TABLES_SQL))
    db.commit()

    count = db.execute(text("SELECT COUNT(*) AS c FROM Pregunta")).mappings().first()
    if count["c"] == 0:
        now = datetime.utcnow()
        for texto, categoria, tipo, opciones, solo_lid, ambiente in PREGUNTAS_BASE + PREGUNTAS_AMBIENTE_GENERAL:
            opciones_final = opciones if opciones is not None else (ESCALA_ESTANDAR if tipo == "escala" else None)
            opciones_json = json.dumps(opciones_final, ensure_ascii=False) if opciones_final is not None else None
            db.execute(text("""
                INSERT INTO Pregunta
                    (texto, categoria, tipo, opcionesEscala, soloLiderazgo, esAmbienteGeneral, activo, createdAt)
                VALUES
                    (:texto, :categoria, :tipo, :opciones, :solo_lid, :ambiente, 1, :now)
            """), {
                "texto": texto, "categoria": categoria, "tipo": tipo,
                "opciones": opciones_json, "solo_lid": solo_lid, "ambiente": ambiente, "now": now,
            })
        db.commit()
```

- [ ] **Step 4: Agregar `get_preguntas()` con filtros opcionales**

```python
def get_preguntas(db: Session, solo_liderazgo: bool | None = None, es_ambiente_general: bool | None = None) -> list[dict]:
    """Lista preguntas activas, con filtros opcionales por soloLiderazgo / esAmbienteGeneral."""
    query = "SELECT id, texto, categoria, tipo, opcionesEscala, soloLiderazgo, esAmbienteGeneral FROM Pregunta WHERE activo = 1"
    params = {}
    if solo_liderazgo is not None:
        query += " AND soloLiderazgo = :solo_lid"
        params["solo_lid"] = 1 if solo_liderazgo else 0
    if es_ambiente_general is not None:
        query += " AND esAmbienteGeneral = :ambiente"
        params["ambiente"] = 1 if es_ambiente_general else 0
    query += " ORDER BY categoria ASC, id ASC"

    rows = db.execute(text(query), params).mappings().all()
    result = []
    for r in rows:
        row = dict(r)
        row["opcionesEscala"] = json.loads(row["opcionesEscala"]) if row["opcionesEscala"] else None
        row["soloLiderazgo"] = bool(row["soloLiderazgo"])
        row["esAmbienteGeneral"] = bool(row["esAmbienteGeneral"])
        result.append(row)
    return result
```

- [ ] **Step 5: Verificar que el módulo importa sin errores de sintaxis**

Run: `py -m py_compile app/database/feedback_preguntas.py`
Expected: sin salida (compila limpio).

- [ ] **Step 6: Commit**

```bash
git add app/database/feedback_preguntas.py
git commit -m "feat: agregar tabla Pregunta/RespuestaFeedback y sembrar banco de preguntas de Feedback 360"
```

---

### Task 2: Endpoint de lectura `GET /feedback/preguntas`

**Files:**
- Modify: `app/routes/feedback.py`

**Interfaces:**
- Consumes: `ensure_table` y `get_preguntas` de `app.database.feedback_preguntas` (Task 1).
- Produces: `GET /feedback/preguntas` → `{"preguntas": [{id, texto, categoria, tipo, opcionesEscala, soloLiderazgo, esAmbienteGeneral}, ...]}`.

- [ ] **Step 1: Agregar el import al principio de `app/routes/feedback.py`**

Ubicar el bloque de imports (líneas 17-22 del archivo actual) y agregar debajo de la línea `from datetime import datetime, timezone`:

```python
from app.database.feedback_preguntas import ensure_table as ensure_preguntas_table, get_preguntas
```

- [ ] **Step 2: Agregar el endpoint al final del archivo**

Agregar al final de `app/routes/feedback.py` (después del cierre de `get_received_feedback`, que termina en la línea 327 actual):

```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/preguntas — Banco de preguntas de Feedback 360
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/preguntas", dependencies=[Depends(require_any_auth)])
def list_preguntas(
    soloLiderazgo: bool | None = None,
    esAmbienteGeneral: bool | None = None,
    db: Session = Depends(get_db),
):
    """Lista el banco de preguntas activas, con filtros opcionales."""
    ensure_preguntas_table(db)
    preguntas = get_preguntas(db, solo_liderazgo=soloLiderazgo, es_ambiente_general=esAmbienteGeneral)
    return {"preguntas": preguntas}
```

- [ ] **Step 3: Verificar que el router importa sin errores**

Run: `py -m py_compile app/routes/feedback.py`
Expected: sin salida (compila limpio).

- [ ] **Step 4: Commit**

```bash
git add app/routes/feedback.py
git commit -m "feat: agregar endpoint GET /feedback/preguntas para el banco de preguntas"
```

---

### Task 3: Verificación manual

No hay test suite automatizado en el repo backend — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend (`uvicorn app.main:app --reload` o el comando que uses normalmente) y confirmar que arranca sin error.
- [ ] **Step 2:** Hacer un request autenticado a `GET /feedback/preguntas` y confirmar que devuelve 39 preguntas (30 base + 8 de ambiente + verificar que no cuenta la #5 faltante, o sea exactamente 38 — ver nota abajo).
  - Nota: `PREGUNTAS_BASE` tiene 30 elementos (no 31 — la #5 nunca fue especificada) + `PREGUNTAS_AMBIENTE_GENERAL` tiene 8 elementos = **38 preguntas totales** sembradas. Confirmar `SELECT COUNT(*) FROM Pregunta` = 38.
- [ ] **Step 3:** `GET /feedback/preguntas?soloLiderazgo=true` devuelve exactamente 5 preguntas (categoría Liderazgo).
- [ ] **Step 4:** `GET /feedback/preguntas?esAmbienteGeneral=true` devuelve exactamente 8 preguntas.
- [ ] **Step 5:** Confirmar en la respuesta que las preguntas de categoría "Confianza" traen su propio `opcionesEscala` (`["Totalmente","Sí","Parcialmente","Poco","No"]` y `["Sí, sin dudas","Sí","Me es indiferente","Preferiría que no","Definitivamente no"]`), y que las de "Preguntas abiertas" traen `tipo: "texto_libre"` y `opcionesEscala: null`.
- [ ] **Step 6:** Confirmar que `/feedback/submit`, `/feedback/peers/{id}`, `/feedback/status/{id}`, `/feedback/received/{id}` siguen respondiendo igual que antes (no se tocaron en este plan).
