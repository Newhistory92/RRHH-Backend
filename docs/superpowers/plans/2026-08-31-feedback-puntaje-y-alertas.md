# Puntaje de Feedback 360 y alertas de conducta — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir las respuestas de `RespuestaFeedback` en un puntaje de feedback por empleado con piso de 3 evaluadores, más alertas de conducta separadas del promedio, corrigiendo de paso que 12 preguntas de polaridad invertida se promedien hoy como si fueran directas.

**Architecture:** Una columna nueva en `Pregunta` marca la polaridad. Tres funciones puras — normalización, puntaje y alertas — viven en un servicio sin I/O, testeable sin base, siguiendo el patrón de `app/services/asistencia_calc.py`. Dos endpoints exponen el resultado y el frontend suma una columna al ranking.

**Tech Stack:** FastAPI + SQLAlchemy Core (`text()`) + SQL Server en `Backend_RRHH`; Next.js 15 + TypeScript + PrimeReact DataTable en `RRHH`; pytest con `FakeSession` de `tests/fakes.py`.

## Global Constraints

- **No levantar servidor.** Verificación por `venv/Scripts/python.exe -m pytest tests/ -q` (siempre acotado a `tests/`, nunca `pytest` pelado — hay scripts sueltos en la raíz que cuelgan) y `npx tsc --noEmit` en el frontend.
- **Ningún test toca bases reales.** Usar `FakeSession` de `tests/fakes.py`.
- **DDL idempotente.** Columna nueva con `IF COL_LENGTH(...) IS NULL`, patrón de `app/database/score_exencion.py`.
- **Cero IDs de rol hardcodeados.** La autorización va por `require_permission(...)`.
- **`Employee.productivityScore` no se toca.** Ni la columna, ni `sync_productivity_scores`, ni ninguna pantalla que hoy la lea.
- **Escala de salida 1–5**, la misma en que se responde. Nunca convertir a base 10.
- **`MIN_EVALUADORES = 3`** gobierna puntaje **y** alertas por igual. No existe el estado "sin puntaje pero con alerta".
- **Línea base de TypeScript: 27 errores preexistentes.** El frontend no debe agregar ninguno.
- Los comentarios de código van **en castellano sin tildes**, siguiendo el estilo del repo.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `app/database/feedback_preguntas.py` (modificar) | Columna `esInversa`, seed y migración de las 12 preguntas invertidas, `normalizar_valor` |
| `app/services/feedback_score.py` (crear) | Funciones puras: puntaje de desempeño y alertas de conducta. Sin I/O |
| `app/routes/feedback.py` (modificar) | Carga las respuestas, delega al servicio, expone los endpoints |
| `src/app/Interfas/Interfaces.ts` (modificar) | Campos de feedback en `StatsEmployee` |
| `src/app/Componentes/ComponEstadistica/Productivity.tsx` (modificar) | Columna "Feedback" en el ranking |
| `src/app/screens/Estadisticas/Screen.tsx` (modificar) | Trae los puntajes y los mezcla en las filas |

---

## Task 1: Polaridad de las preguntas

**Files:**
- Modify: `app/database/feedback_preguntas.py`
- Test: `tests/test_feedback_polaridad.py`

**Interfaces:**
- Produces: `normalizar_valor(valor: int, es_inversa: bool) -> int`; `PREGUNTAS_INVERSAS: tuple[str, ...]`; `ensure_table` marca `esInversa` en la base; `get_preguntas` devuelve `esInversa: bool` en cada dict.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_feedback_polaridad.py`:

```python
"""
Polaridad de las preguntas de Feedback 360.

El banco mezcla preguntas donde 5 es bueno ("¿trata con respeto?") con otras
donde 5 es malo ("¿genera conflictos innecesarios?"), y hasta este cambio no
habia forma de distinguirlas: el promedio las sumaba igual, asi que la peor
respuesta posible aparecia como fortaleza.
"""

from app.database.feedback_preguntas import (
    PREGUNTAS_AMBIENTE_GENERAL,
    PREGUNTAS_BASE,
    PREGUNTAS_INVERSAS,
    normalizar_valor,
)


def test_una_pregunta_directa_no_cambia_el_valor():
    assert normalizar_valor(5, es_inversa=False) == 5
    assert normalizar_valor(1, es_inversa=False) == 1


def test_una_pregunta_inversa_da_vuelta_la_escala():
    assert normalizar_valor(5, es_inversa=True) == 1
    assert normalizar_valor(1, es_inversa=True) == 5
    assert normalizar_valor(4, es_inversa=True) == 2
    assert normalizar_valor(2, es_inversa=True) == 4


def test_el_punto_medio_no_cambia_en_ninguna_de_las_dos():
    assert normalizar_valor(3, es_inversa=False) == 3
    assert normalizar_valor(3, es_inversa=True) == 3


def test_normalizar_siempre_deja_cinco_como_lo_mejor():
    for valor in range(1, 6):
        for inversa in (True, False):
            assert 1 <= normalizar_valor(valor, inversa) <= 5


def test_son_doce_preguntas_inversas():
    assert len(PREGUNTAS_INVERSAS) == 12


def test_cada_pregunta_inversa_existe_en_el_banco():
    """Un texto mal copiado dejaria la pregunta sin marcar y el bug vivo."""
    textos = {p[0] for p in PREGUNTAS_BASE + PREGUNTAS_AMBIENTE_GENERAL}
    for texto in PREGUNTAS_INVERSAS:
        assert texto in textos, f"'{texto}' no coincide con ninguna pregunta del banco"


def test_la_pregunta_positiva_de_riesgos_no_esta_marcada():
    """En Riesgos laborales hay una directa: un 5 ahi es bueno."""
    assert "¿Te sentís cómodo trabajando con esta persona?" not in PREGUNTAS_INVERSAS
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_feedback_polaridad.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'PREGUNTAS_INVERSAS'`.

- [ ] **Step 3: Agregar la constante y la función**

En `app/database/feedback_preguntas.py`, después de `PREGUNTAS_AMBIENTE_GENERAL`:

```python
# Preguntas donde un valor alto es MALO. Con la escala estandar
# ["Siempre", "Casi siempre", "Algunas veces", "Rara vez", "Nunca"] mapeada a
# 5..1, responder "Siempre" a "¿genera conflictos?" da un 5 que, sin invertir,
# sube el promedio de la persona.
#
# Es la unica fuente de verdad: la usan el seed de preguntas nuevas y la
# migracion de las ya sembradas.
PREGUNTAS_INVERSAS: tuple[str, ...] = (
    "¿Has presenciado conductas inapropiadas por parte de esta persona?",
    "¿Genera conflictos innecesarios?",
    "¿Su trabajo genera retrabajos para otros?",
    "¿Alguna persona del equipo genera un ambiente tenso?",
    "¿Evitás interactuar con esta persona cuando es posible?",
    "¿Considerás que esta persona afecta negativamente al equipo?",
    "¿Has observado faltas de respeto hacia compañeros?",
    "¿Has observado conductas intimidantes o agresivas?",
    "¿Creés que esta persona discrimina o hace comentarios ofensivos?",
    "¿Existe favoritismo?",
    "¿Te sentís sobrecargado de trabajo?",
    "¿Has pensado en renunciar por el ambiente laboral?",
)


def normalizar_valor(valor: int, es_inversa: bool) -> int:
    """
    Deja la escala con 5 = mejor y 1 = peor, sea cual sea la polaridad.

    Todo lo que consume respuestas opera sobre el valor normalizado y no
    vuelve a preocuparse por como estaba redactada la pregunta.
    """
    return 6 - valor if es_inversa else valor
```

- [ ] **Step 4: Correr el test para verificar que pasa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_feedback_polaridad.py -v
```

Esperado: PASS, 7 tests.

- [ ] **Step 5: Agregar la columna a la tabla**

En `app/database/feedback_preguntas.py`, agregar después de `CREATE_TABLES_SQL`:

```python
# La columna se agrega aparte del CREATE porque Pregunta ya existe en las
# instalaciones actuales, con 38 filas sembradas antes de que hubiera
# polaridad.
ALTER_ESINVERSA_SQL = """
IF COL_LENGTH('Pregunta','esInversa') IS NULL
ALTER TABLE Pregunta ADD esInversa BIT NOT NULL DEFAULT 0;
"""
```

- [ ] **Step 6: Sembrar y migrar la polaridad en `ensure_table`**

Reemplazar el cuerpo de `ensure_table` por:

```python
def ensure_table(db: Session) -> None:
    """Crea Pregunta y RespuestaFeedback si no existen, siembra el banco solo
    si Pregunta esta vacia (no duplica ni pisa preguntas desactivadas a mano),
    y marca la polaridad tanto en las nuevas como en las ya sembradas."""
    db.execute(text(CREATE_TABLES_SQL))
    db.commit()
    db.execute(text(ALTER_ESINVERSA_SQL))
    db.commit()

    count = db.execute(text("SELECT COUNT(*) AS c FROM Pregunta")).mappings().first()
    if count["c"] == 0:
        now = datetime.utcnow()
        for texto, categoria, tipo, opciones, solo_lid, ambiente in PREGUNTAS_BASE + PREGUNTAS_AMBIENTE_GENERAL:
            opciones_final = opciones if opciones is not None else (ESCALA_ESTANDAR if tipo == "escala" else None)
            opciones_json = json.dumps(opciones_final, ensure_ascii=False) if opciones_final is not None else None
            db.execute(text("""
                INSERT INTO Pregunta
                    (texto, categoria, tipo, opcionesEscala, soloLiderazgo, esAmbienteGeneral, esInversa, activo, createdAt)
                VALUES
                    (:texto, :categoria, :tipo, :opciones, :solo_lid, :ambiente, :inversa, 1, :now)
            """), {
                "texto": texto, "categoria": categoria, "tipo": tipo,
                "opciones": opciones_json, "solo_lid": solo_lid, "ambiente": ambiente,
                "inversa": 1 if texto in PREGUNTAS_INVERSAS else 0, "now": now,
            })
        db.commit()

    # Migracion de las instalaciones que ya tenian el banco sembrado sin
    # polaridad. Idempotente: reafirma el valor correcto en cada arranque.
    for texto in PREGUNTAS_INVERSAS:
        db.execute(text(
            "UPDATE Pregunta SET esInversa = 1 WHERE texto = :texto AND esInversa = 0"
        ), {"texto": texto})
    db.commit()
```

- [ ] **Step 7: Devolver `esInversa` en `get_preguntas`**

En `get_preguntas`, cambiar el `SELECT` y el armado del dict:

```python
    query = "SELECT id, texto, categoria, tipo, opcionesEscala, soloLiderazgo, esAmbienteGeneral, esInversa FROM Pregunta WHERE activo = 1"
```

y dentro del `for r in rows:`, después de `row["esAmbienteGeneral"] = bool(row["esAmbienteGeneral"])`:

```python
        row["esInversa"] = bool(row["esInversa"])
```

- [ ] **Step 8: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: todo verde. Los 7 nuevos sumados al total previo (323).

- [ ] **Step 9: Commit**

```bash
git add app/database/feedback_preguntas.py tests/test_feedback_polaridad.py
git commit -m "feat(feedback): marcar la polaridad de las preguntas invertidas"
```

---

## Task 2: Motor de puntaje y alertas

**Files:**
- Create: `app/services/feedback_score.py`
- Test: `tests/test_feedback_score.py`

**Interfaces:**
- Consumes: nada de Task 1 en tiempo de ejecución — recibe valores ya normalizados.
- Produces: `RespuestaNorm`, `PuntajeFeedback`, `AlertaConducta`, `puntaje_feedback(respuestas: list[RespuestaNorm]) -> PuntajeFeedback`, `detectar_alertas(respuestas: list[RespuestaNorm]) -> list[AlertaConducta]`, `CATEGORIAS_DESEMPENO`, `CATEGORIAS_RIESGO`, `MIN_EVALUADORES`, `UMBRAL_ALERTA`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_feedback_score.py`:

```python
"""
Motor de puntaje de Feedback 360 y alertas de conducta.

Funciones puras: reciben respuestas ya normalizadas y devuelven el puntaje y
las banderas. Sin base de datos, para que las reglas delicadas -piso de
evaluadores, exclusion de categorias de riesgo- se prueben sin fixtures.
"""

from app.services.feedback_score import (
    MIN_EVALUADORES,
    UMBRAL_ALERTA,
    RespuestaNorm,
    detectar_alertas,
    puntaje_feedback,
)


def _r(evaluador, valor, categoria="Responsabilidad", riesgo=False, texto="¿Cumple?"):
    return RespuestaNorm(
        evaluadorId=evaluador, categoria=categoria, valor=valor,
        esRiesgo=riesgo, preguntaTexto=texto,
    )


# -- Piso de evaluadores -------------------------------------------------------

def test_con_dos_evaluadores_no_hay_puntaje():
    r = puntaje_feedback([_r(1, 5), _r(2, 5)])
    assert r.promedio is None
    assert r.suficiente is False
    assert r.evaluadores == 2
    assert r.porCategoria == {}


def test_con_tres_evaluadores_si_hay_puntaje():
    r = puntaje_feedback([_r(1, 4), _r(2, 4), _r(3, 4)])
    assert r.suficiente is True
    assert r.promedio == 4.0
    assert r.evaluadores == 3


def test_un_evaluador_que_responde_muchas_preguntas_cuenta_como_uno():
    respuestas = [_r(1, 5) for _ in range(30)]
    r = puntaje_feedback(respuestas)
    assert r.evaluadores == 1
    assert r.suficiente is False


def test_sin_respuestas_no_hay_puntaje():
    r = puntaje_feedback([])
    assert r.promedio is None
    assert r.evaluadores == 0


# -- Que entra al promedio -----------------------------------------------------

def test_las_categorias_de_riesgo_no_entran_al_promedio():
    """
    Un 1 en conducta no debe bajar el promedio de desempeno: se informa como
    alerta aparte, para que no se diluya ni se compense con puntualidad.
    """
    respuestas = [
        _r(1, 5), _r(2, 5), _r(3, 5),
        _r(1, 1, categoria="Conductas de riesgo", riesgo=True),
    ]
    r = puntaje_feedback(respuestas)
    assert r.promedio == 5.0


def test_el_promedio_se_desglosa_por_categoria():
    respuestas = [
        _r(1, 5, categoria="Comunicación"), _r(2, 5, categoria="Comunicación"),
        _r(3, 5, categoria="Comunicación"),
        _r(1, 3, categoria="Responsabilidad"), _r(2, 3, categoria="Responsabilidad"),
        _r(3, 3, categoria="Responsabilidad"),
    ]
    r = puntaje_feedback(respuestas)
    assert r.porCategoria["Comunicación"] == 5.0
    assert r.porCategoria["Responsabilidad"] == 3.0
    assert r.promedio == 4.0


def test_un_valor_invertido_baja_el_promedio():
    """
    Regresion del bug: "genera conflictos = Siempre" llega aca ya normalizado
    a 1 y tiene que bajar el promedio, no subirlo.
    """
    buenos = [_r(1, 5), _r(2, 5), _r(3, 5)]
    con_malo = buenos + [_r(1, 1, texto="¿Genera conflictos innecesarios?")]
    assert puntaje_feedback(con_malo).promedio < puntaje_feedback(buenos).promedio


# -- Alertas -------------------------------------------------------------------

def test_sin_el_piso_de_evaluadores_no_se_devuelven_alertas():
    respuestas = [_r(1, 1, categoria="Conductas de riesgo", riesgo=True)]
    assert detectar_alertas(respuestas) == []


def test_con_el_piso_alcanzado_un_solo_reporte_ya_alerta():
    respuestas = [
        _r(1, 5), _r(2, 5), _r(3, 5),
        _r(1, 1, categoria="Conductas de riesgo", riesgo=True, texto="¿Discrimina?"),
    ]
    alertas = detectar_alertas(respuestas)
    assert len(alertas) == 1
    assert alertas[0].preguntaTexto == "¿Discrimina?"
    assert alertas[0].reportan == 1
    assert alertas[0].evaluadores == 3


def test_el_umbral_marca_las_dos_peores_respuestas():
    base = [_r(1, 5), _r(2, 5), _r(3, 5)]
    riesgo = dict(categoria="Conductas de riesgo", riesgo=True, texto="¿Discrimina?")

    assert len(detectar_alertas(base + [_r(1, 3, **riesgo)])) == 0
    assert len(detectar_alertas(base + [_r(1, 2, **riesgo)])) == 1
    assert len(detectar_alertas(base + [_r(1, 1, **riesgo)])) == 1
    assert UMBRAL_ALERTA == 2


def test_las_categorias_de_desempeno_nunca_generan_alertas():
    respuestas = [_r(1, 1), _r(2, 1), _r(3, 1)]
    assert detectar_alertas(respuestas) == []


def test_varios_reportes_de_la_misma_pregunta_se_agrupan():
    respuestas = [
        _r(1, 5), _r(2, 5), _r(3, 5),
        _r(1, 1, categoria="Conductas de riesgo", riesgo=True, texto="¿Discrimina?"),
        _r(2, 2, categoria="Conductas de riesgo", riesgo=True, texto="¿Discrimina?"),
    ]
    alertas = detectar_alertas(respuestas)
    assert len(alertas) == 1
    assert alertas[0].reportan == 2
    assert alertas[0].evaluadores == 3


def test_el_piso_cuenta_evaluadores_de_riesgo_tambien():
    """
    El piso mide participacion del grupo -cuanta gente evaluo a la persona-,
    que es lo que protege el anonimato, no cuantas respuestas alimentan el
    promedio.
    """
    riesgo = dict(categoria="Riesgos laborales", riesgo=True, texto="¿Lo evitas?")
    respuestas = [_r(1, 5), _r(2, 5), _r(3, 1, **riesgo)]
    r = puntaje_feedback(respuestas)
    assert r.evaluadores == 3
    assert r.suficiente is True
    assert MIN_EVALUADORES == 3
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_feedback_score.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.services.feedback_score'`.

- [ ] **Step 3: Escribir el servicio**

Crear `app/services/feedback_score.py`:

```python
"""
Puntaje de Feedback 360 y alertas de conducta.

Funciones puras: no tocan la base ni conocen el esquema. Reciben respuestas
con el valor YA normalizado (5 = mejor, 1 = peor; ver
feedback_preguntas.normalizar_valor) y devuelven el puntaje y las banderas.

Dos reglas gobiernan todo el modulo:

1. Piso de participacion. Con menos de MIN_EVALUADORES evaluadores distintos
   no se devuelve nada -ni puntaje ni alertas-. Con menos, el numero seria la
   opinion de una o dos personas presentada como medicion, y ademas en un
   grupo chico haria deducible quien evaluo, rompiendo el anonimato que la
   pantalla le promete al que responde.

2. La conducta no se promedia con el desempeno. Las categorias de riesgo
   quedan fuera del puntaje y salen como alertas propias: una senal de
   discriminacion no debe diluirse en unas decimas ni volverse compensable
   con puntualidad.
"""

from collections import defaultdict
from dataclasses import dataclass, field

# Categorias que miden desempeno y entran al promedio.
CATEGORIAS_DESEMPENO = frozenset({
    "Respeto y convivencia",
    "Comunicación",
    "Responsabilidad",
    "Profesionalismo",
    "Liderazgo",
    "Confianza",
})

# Categorias que miden conducta y salen como alertas.
CATEGORIAS_RIESGO = frozenset({
    "Riesgos laborales",
    "Conductas de riesgo",
})

# "Ambiente laboral general" y "Preguntas abiertas" no estan en ninguno de los
# dos conjuntos a proposito: la primera no habla de una persona (se responde
# sin evaluado) y la segunda es texto libre, sin valor numerico.

MIN_EVALUADORES = 3

# Sobre el valor normalizado: marca las dos peores respuestas posibles. Con la
# escala estandar, una pregunta inversa contestada "Casi siempre" (4 crudo)
# normaliza a 2 y alerta; "Algunas veces" (3) normaliza a 3 y no. El medio
# ambiguo no dispara.
UMBRAL_ALERTA = 2


@dataclass(frozen=True)
class RespuestaNorm:
    """Una respuesta de escala sobre una persona, ya normalizada."""
    evaluadorId: int
    categoria: str
    valor: int
    esRiesgo: bool
    preguntaTexto: str


@dataclass(frozen=True)
class PuntajeFeedback:
    promedio: float | None
    evaluadores: int
    suficiente: bool
    porCategoria: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertaConducta:
    preguntaTexto: str
    categoria: str
    reportan: int
    evaluadores: int


def _evaluadores_distintos(respuestas: list[RespuestaNorm]) -> int:
    """
    Cuenta personas, no respuestas: quien contesta 30 preguntas sigue siendo
    un evaluador. Incluye las respuestas de riesgo, porque el piso mide
    participacion del grupo y no cuantas alimentan el promedio.
    """
    return len({r.evaluadorId for r in respuestas})


def puntaje_feedback(respuestas: list[RespuestaNorm]) -> PuntajeFeedback:
    """Promedio de desempeno en escala 1-5, o None si no llega al piso."""
    evaluadores = _evaluadores_distintos(respuestas)
    if evaluadores < MIN_EVALUADORES:
        return PuntajeFeedback(promedio=None, evaluadores=evaluadores, suficiente=False)

    desempeno = [r for r in respuestas if not r.esRiesgo]
    if not desempeno:
        return PuntajeFeedback(promedio=None, evaluadores=evaluadores, suficiente=False)

    por_categoria: dict[str, list[int]] = defaultdict(list)
    for r in desempeno:
        por_categoria[r.categoria].append(r.valor)

    promedios = {
        categoria: round(sum(valores) / len(valores), 2)
        for categoria, valores in por_categoria.items()
    }

    # El promedio general se calcula sobre las respuestas, no sobre los
    # promedios por categoria: una categoria con una sola pregunta no debe
    # pesar lo mismo que una de cinco.
    general = round(sum(r.valor for r in desempeno) / len(desempeno), 2)

    return PuntajeFeedback(
        promedio=general,
        evaluadores=evaluadores,
        suficiente=True,
        porCategoria=promedios,
    )


def detectar_alertas(respuestas: list[RespuestaNorm]) -> list[AlertaConducta]:
    """
    Banderas de conducta para RRHH, agrupadas por pregunta.

    Comparte el piso de participacion con el puntaje, asi que ambos se
    habilitan juntos: no existe el estado "sin puntaje pero con alerta".
    Alcanzado el piso, un solo reporte ya genera alerta -no se exige que
    otros lo corroboren- y se informa el respaldo para que RRHH calibre.
    """
    evaluadores = _evaluadores_distintos(respuestas)
    if evaluadores < MIN_EVALUADORES:
        return []

    por_pregunta: dict[tuple[str, str], set[int]] = defaultdict(set)
    for r in respuestas:
        if r.esRiesgo and r.valor <= UMBRAL_ALERTA:
            por_pregunta[(r.preguntaTexto, r.categoria)].add(r.evaluadorId)

    return [
        AlertaConducta(
            preguntaTexto=texto,
            categoria=categoria,
            reportan=len(ids),
            evaluadores=evaluadores,
        )
        for (texto, categoria), ids in sorted(
            por_pregunta.items(), key=lambda kv: (-len(kv[1]), kv[0][0])
        )
    ]
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_feedback_score.py -v
```

Esperado: PASS, 13 tests.

- [ ] **Step 5: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add app/services/feedback_score.py tests/test_feedback_score.py
git commit -m "feat(feedback): motor de puntaje y alertas de conducta"
```

---

## Task 3: Endpoints

**Files:**
- Modify: `app/routes/feedback.py`
- Test: `tests/test_feedback_endpoints.py`

**Interfaces:**
- Consumes: `normalizar_valor`, `PREGUNTAS_INVERSAS` de Task 1; `RespuestaNorm`, `puntaje_feedback`, `detectar_alertas`, `CATEGORIAS_RIESGO` de Task 2.
- Produces: `cargar_respuestas_normalizadas(db, periodo) -> dict[int, list[RespuestaNorm]]`; `GET /feedback/puntajes`; `GET /feedback/received/{id}` corregido.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_feedback_endpoints.py`:

```python
"""
Endpoints de puntaje de feedback.

Los handlers se invocan directamente, sin servidor HTTP, siguiendo el patron
de tests/test_score_exencion_endpoint.py.
"""

from datetime import date

from app.routes.feedback import cargar_respuestas_normalizadas
from tests.fakes import FakeSession

FRAG = "FROM RespuestaFeedback rf"


def _fila(evaluado, evaluador, valor, categoria, inversa, texto="¿Cumple?"):
    return {
        "evaluadoEmployeeId": evaluado, "evaluadorEmployeeId": evaluador,
        "valorEscala": valor, "categoria": categoria,
        "esInversa": inversa, "texto": texto,
    }


def test_agrupa_las_respuestas_por_evaluado():
    db = FakeSession({FRAG: [
        _fila(3, 1, 5, "Responsabilidad", False),
        _fila(9, 1, 4, "Responsabilidad", False),
    ]})
    r = cargar_respuestas_normalizadas(db, date(2026, 7, 1))
    assert set(r.keys()) == {3, 9}


def test_aplica_la_polaridad_al_cargar():
    """Una inversa con 5 crudo tiene que llegar al motor como 1."""
    db = FakeSession({FRAG: [
        _fila(3, 1, 5, "Responsabilidad", True, "¿Genera conflictos innecesarios?"),
    ]})
    r = cargar_respuestas_normalizadas(db, date(2026, 7, 1))
    assert r[3][0].valor == 1


def test_marca_las_categorias_de_riesgo():
    db = FakeSession({FRAG: [
        _fila(3, 1, 5, "Conductas de riesgo", False),
        _fila(3, 1, 5, "Responsabilidad", False),
    ]})
    r = cargar_respuestas_normalizadas(db, date(2026, 7, 1))
    assert [x.esRiesgo for x in r[3]] == [True, False]


def test_sin_respuestas_devuelve_diccionario_vacio():
    db = FakeSession({FRAG: []})
    assert cargar_respuestas_normalizadas(db, date(2026, 7, 1)) == {}
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_feedback_endpoints.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'cargar_respuestas_normalizadas'`.

- [ ] **Step 3: Agregar los imports**

En `app/routes/feedback.py`, junto a los imports existentes de `app.database.feedback_preguntas`:

```python
from app.database.feedback_preguntas import (
    ensure_table as ensure_preguntas_table,
    get_preguntas,
    normalizar_valor,
)
from app.services.feedback_score import (
    CATEGORIAS_RIESGO,
    RespuestaNorm,
    detectar_alertas,
    puntaje_feedback,
)
```

- [ ] **Step 4: Escribir el cargador**

En `app/routes/feedback.py`, después de `pares_aplicables`:

```python
def cargar_respuestas_normalizadas(db: Session, periodo) -> dict[int, list[RespuestaNorm]]:
    """
    Respuestas de escala del periodo, agrupadas por evaluado y ya
    normalizadas por polaridad.

    Excluye las de ambiente general: no hablan de una persona, se responden
    sin evaluado. El texto libre queda fuera por no tener valor numerico.
    """
    filas = db.execute(text("""
        SELECT rf.evaluadoEmployeeId, rf.evaluadorEmployeeId, rf.valorEscala,
               p.categoria, p.esInversa, p.texto
        FROM RespuestaFeedback rf
        INNER JOIN Pregunta p ON p.id = rf.preguntaId
        WHERE rf.periodo = :periodo
          AND rf.evaluadoEmployeeId IS NOT NULL
          AND rf.valorEscala IS NOT NULL
          AND p.tipo = 'escala'
          AND p.esAmbienteGeneral = 0
    """), {"periodo": periodo}).mappings().all()

    por_evaluado: dict[int, list[RespuestaNorm]] = {}
    for f in filas:
        categoria = f["categoria"]
        por_evaluado.setdefault(int(f["evaluadoEmployeeId"]), []).append(
            RespuestaNorm(
                evaluadorId=int(f["evaluadorEmployeeId"]),
                categoria=categoria,
                valor=normalizar_valor(int(f["valorEscala"]), bool(f["esInversa"])),
                esRiesgo=categoria in CATEGORIAS_RIESGO,
                preguntaTexto=f["texto"],
            )
        )
    return por_evaluado
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_feedback_endpoints.py -v
```

Esperado: PASS, 4 tests.

- [ ] **Step 6: Agregar el endpoint bulk**

En `app/routes/feedback.py`, después de `get_feedback_status`:

```python
@router.get("/puntajes", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def get_puntajes_feedback(db: Session = Depends(get_db)):
    """
    Puntaje de feedback de todos los empleados del periodo, para el ranking.

    Requiere rrhh.gestionar y no feedback.participar: este ultimo lo tiene
    todo el personal (esta en _BASE), y el puntaje de terceros es dato de
    RRHH. No devuelve el texto de las alertas, solo cuantas hay; el detalle
    se pide por empleado.
    """
    ensure_preguntas_table(db)
    ensure_config_table(db)
    periodo = get_periodo_actual(db)

    por_evaluado = cargar_respuestas_normalizadas(db, periodo)

    puntajes = []
    for employee_id, respuestas in por_evaluado.items():
        p = puntaje_feedback(respuestas)
        puntajes.append({
            "employeeId": employee_id,
            "promedio": p.promedio,
            "evaluadores": p.evaluadores,
            "suficiente": p.suficiente,
            "alertas": len(detectar_alertas(respuestas)),
        })

    return {"periodo": periodo.isoformat(), "puntajes": puntajes}
```

- [ ] **Step 7: Corregir `/received/{employee_id}`**

**Sobre el permiso.** El spec dice "subir el permiso a `rrhh.gestionar` para lectura de terceros". Se implementa con el `_check_self_or_admin` que ya existe en este router, que permite al propio empleado o a quien tenga `feedback.configurar`. Es equivalente en efecto —verificado en `app/permisos.py`: `feedback.configurar` lo tienen solo RRHH y ADMIN (vía comodín), no está en `_BASE`— y evita introducir un segundo patrón de autorización en un router que ya usa ese helper en los otros cuatro endpoints. El agujero que se cierra es que este endpoint **no llamaba a ningún chequeo**.

Reemplazar la firma y el cálculo de categorías de `get_received_feedback`. La firma pasa a exigir el usuario actual y a chequear identidad:

```python
@router.get("/received/{employee_id}", dependencies=[Depends(require_permission("feedback.participar"))])
def get_received_feedback(employee_id: int, db: Session = Depends(get_db),
                          current_user: dict = Depends(get_current_user)):
    """
    Indicadores de Feedback 360 recibidos por el empleado.

    Antes cualquiera con feedback.participar -o sea todo el personal- podia
    leer el feedback de cualquier otro pasando su id: faltaba el chequeo de
    identidad que si tienen los demas endpoints del router.

    Los promedios se calculan sobre valores normalizados y solo con
    categorias de desempeno. Sin normalizar, una respuesta "siempre genera
    conflictos" subia el promedio y la categoria aparecia como fortaleza.
    """
    _check_self_or_admin(employee_id, current_user)

    ensure_preguntas_table(db)
    ensure_config_table(db)

    periodo_actual = get_periodo_actual(db)
    respuestas = cargar_respuestas_normalizadas(db, periodo_actual).get(employee_id, [])
    p = puntaje_feedback(respuestas)

    ranking = sorted(
        ({"categoria": c, "promedio": v} for c, v in p.porCategoria.items()),
        key=lambda x: x["promedio"], reverse=True,
    )

    return {
        "employeeId": employee_id,
        "promedio": p.promedio,
        "evaluadores": p.evaluadores,
        "suficiente": p.suficiente,
        "fortalezas": ranking[:5],
        "debilidades": list(reversed(ranking))[:5],
        "alertas": [
            {
                "pregunta": a.preguntaTexto,
                "categoria": a.categoria,
                "reportan": a.reportan,
                "evaluadores": a.evaluadores,
            }
            for a in detectar_alertas(respuestas)
        ],
    }
```

Nota: el bloque de `evolucion` (promedio del período anterior) se elimina. Comparar contra el período anterior exige normalizar también ese período y el spec acota esta iteración al actual; volver a agregarlo es trabajo de una iteración posterior.

- [ ] **Step 8: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: todo verde. Si algún test viejo asumía la forma anterior de `/received`, actualizarlo — el contrato cambió a propósito.

- [ ] **Step 9: Verificar que la app importa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -c "import app.main; print('IMPORT OK')"
```

Esperado: `IMPORT OK`.

- [ ] **Step 10: Commit**

```bash
git add app/routes/feedback.py tests/test_feedback_endpoints.py
git commit -m "feat(feedback): endpoints de puntaje y correccion de permisos en received"
```

---

## Task 4: Columna en el ranking

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts:373-374`
- Modify: `src/app/screens/Estadisticas/Screen.tsx`
- Modify: `src/app/Componentes/ComponEstadistica/Productivity.tsx:155`

**Interfaces:**
- Consumes: `GET /feedback/puntajes` de Task 3.

- [ ] **Step 1: Agregar los campos al tipo**

En `src/app/Interfas/Interfaces.ts`, junto a `isExento?: boolean;` (línea 374):

```typescript
  isExento?: boolean;
  /** Puntaje de Feedback 360 (1-5). null si no llega al minimo de 3 evaluadores. */
  feedbackPromedio?: number | null;
  feedbackEvaluadores?: number;
  feedbackAlertas?: number;
```

- [ ] **Step 2: Traer los puntajes en el fetch**

En `src/app/screens/Estadisticas/Screen.tsx`, dentro de `fetchData`, agregar la llamada al `Promise.all` existente. El bloque actual pide tres endpoints; agregar el cuarto y mezclar por `employeeId`:

```typescript
      const [dashboardRes, metaRes, globalRes, feedbackRes] = await Promise.all([
        fetch(`${BACKEND_URL}/stats/dashboard`, { headers }),
        fetch(`${BACKEND_URL}/stats/metadata`, { headers }),
        fetch(`${BACKEND_URL}/stats/global-stats`, { headers }),
        fetch(`${BACKEND_URL}/feedback/puntajes`, { headers }),
      ]);
```

Y después de armar `employees`, antes de `setEmployees`:

```typescript
      // El puntaje de feedback vive en su propio endpoint: se mezcla por id.
      // Un 403 no rompe la pantalla -- el ranking sigue sirviendo sin la
      // columna para quien no tiene rrhh.gestionar.
      let porEmpleado = new Map<number, { promedio: number | null; evaluadores: number; alertas: number }>();
      if (feedbackRes.ok) {
        const fb = await feedbackRes.json();
        porEmpleado = new Map(
          (fb.puntajes ?? []).map((p: { employeeId: number; promedio: number | null; evaluadores: number; alertas: number }) =>
            [p.employeeId, { promedio: p.promedio, evaluadores: p.evaluadores, alertas: p.alertas }]
          )
        );
      }
      const conFeedback = employees.map((e: StatsEmployee) => {
        const f = porEmpleado.get(e.id);
        return {
          ...e,
          feedbackPromedio: f ? f.promedio : null,
          feedbackEvaluadores: f ? f.evaluadores : 0,
          feedbackAlertas: f ? f.alertas : 0,
        };
      });
```

Usar `conFeedback` en lugar de `employees` en la llamada a `setEmployees`.

- [ ] **Step 3: Escribir el template de la columna**

En `src/app/Componentes/ComponEstadistica/Productivity.tsx`, después de `productivityBodyTemplate` (línea 155):

```tsx
  // Columna de Feedback 360. Dos estados posibles y solo dos: el puntaje y
  // las alertas comparten el piso de 3 evaluadores, asi que o se muestran
  // ambos o ninguno. No existe "Datos insuficientes" con icono de alerta.
  const feedbackBodyTemplate = (employee: Employee) => {
    const promedio = employee.feedbackPromedio;
    const alertas = employee.feedbackAlertas ?? 0;

    if (promedio == null) {
      return (
        <span
          className="text-sm text-muted-foreground"
          title="Hacen falta al menos 3 evaluadores para mostrar un puntaje. Con menos, el numero seria la opinion de una o dos personas y haria deducible quien evaluo."
        >
          Datos insuficientes
        </span>
      );
    }

    return (
      <div className="flex items-center gap-2">
        <div>
          <span className="font-bold text-lg text-foreground">{promedio.toFixed(1)}</span>
          <p className="text-xs text-muted-foreground">
            {employee.feedbackEvaluadores} evaluadores
          </p>
        </div>
        {alertas > 0 && (
          <span
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium bg-warning-soft text-warning-soft-foreground"
            title={`${alertas} alerta(s) de conducta para revisar por RRHH`}
          >
            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
            {alertas}
          </span>
        )}
      </div>
    );
  };
```

- [ ] **Step 4: Importar el ícono**

En el import de `lucide-react` al tope de `Productivity.tsx`, agregar `AlertTriangle` a la lista existente.

- [ ] **Step 5: Agregar la columna a la tabla**

En el `<DataTable>` de `Productivity.tsx`, después del `<Column field="productivityScore" ... />`:

```tsx
        <Column
          field="feedbackPromedio"
          header="Feedback"
          body={feedbackBodyTemplate}
          style={{ minWidth: '160px' }}
          className="hidden lg:table-cell"
          headerClassName="hidden lg:table-cell"
        />
```

- [ ] **Step 6: Explicar la columna en el modal**

En `src/app/Componentes/ComponEstadistica/ComoSeCalculaModal.tsx`, dentro del bloque "Qué entra en el puntaje", agregar una tercera `<Fila>`:

```tsx
            <Fila
              icon={<MinusCircle size={18} className="text-muted-foreground" />}
              titulo="Feedback 360 — columna aparte, no suma al puntaje"
              detalle="La opinión de los compañeros se muestra en su propia columna. Aparece solo con 3 evaluadores o más: con menos, el número sería la opinión de una o dos personas y permitiría deducir quién evaluó."
            />
```

- [ ] **Step 7: Verificar**

```bash
cd /c/Users/Emiliano/Documents/RRHH && npx tsc --noEmit 2>&1 | grep -c "error TS"
```

Esperado: `27`, la línea base. Ni uno más.

```bash
cd /c/Users/Emiliano/Documents/RRHH && node scripts/check-contrast.mjs
```

Esperado: `Todos los pares cumplen AA.`

```bash
cd /c/Users/Emiliano/Documents/RRHH && npm run build
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(estadisticas): columna de Feedback 360 en el ranking"
```

---

## Verificación final

- [ ] `Backend_RRHH`: `venv/Scripts/python.exe -m pytest tests/ -q` — todo verde, acotado a `tests/`. Total esperado: 323 previos + 24 nuevos = 347.
- [ ] `Backend_RRHH`: `venv/Scripts/python.exe -c "import app.main"` sin error.
- [ ] `RRHH`: `npx tsc --noEmit` en 27 errores, `node scripts/check-contrast.mjs` en verde, `npm run build` exitoso.
- [ ] Confirmar en la base que la migración de polaridad corrió:

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -c "
from app.database.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
n = db.execute(text('SELECT COUNT(*) FROM Pregunta WHERE esInversa = 1')).scalar()
print(f'Preguntas marcadas como inversas: {n} (esperado 12)')
db.close()
"
```

## Nota operativa

Con los datos actuales hay **un solo evaluador**, así que al terminar esta implementación **ni el puntaje ni las alertas se van a mostrar para nadie** — la columna dirá "Datos insuficientes" en todas las filas. Es el comportamiento correcto y esperado, no un fallo. La verificación de esta iteración es por tests.

Para poder verlo funcionando en pantalla hacen falta respuestas de al menos 3 evaluadores distintos sobre una misma persona en el período activo. Eso es carga de datos, no parte de este plan.
