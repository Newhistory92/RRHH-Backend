# Ficha de mérito por gerencia — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Darle a una autoridad, al momento de decidir un ascenso dentro de su gerencia, una ficha comparativa por persona con cada dimensión por separado y su cobertura de datos — en lugar de un número compuesto que esconde de dónde sale.

**Architecture:** El score de actividad corrige su denominador (pasa de eventos por sesión a eventos por hora efectiva) y `ScoreHistorico` guarda con qué fórmula se calculó cada corrida, para que las filas viejas sigan siendo legibles. Turnero expone su productividad ya calculada por un endpoint nuevo — no se reimplementa en RRHH — y Backend_RRHH la consume. La ficha se arma en un servicio puro que recibe las dimensiones y decide qué mostrar y qué marcar como sin datos; no compone un promedio.

**Tech Stack:** FastAPI + SQLAlchemy Core (`text()`) + SQL Server y `requests` en `Backend_RRHH`; Next.js 15 + TypeScript + PrimeReact en `RRHH`; Next.js 15 + Prisma en `Turnero`; pytest con `FakeSession` de `tests/fakes.py`; vitest en Turnero.

## Global Constraints

- **Tres repos.** `C:\Users\Emiliano\Documents\Backend_RRHH`, `C:\Users\Emiliano\Documents\RRHH`, `C:\Users\Emiliano\Documents\Turnero`. Cada uno con su propio commit; nunca un commit que abarque dos.
- **Nunca escribir en la base ObraSocial.** Todo acceso a `[ObraSocial].[dbo].*` es de solo lectura.
- **Nunca escribir en la base Turnero desde RRHH.** La integración es HTTP de solo lectura contra el endpoint nuevo.
- **No levantar servidor** para verificar. Backend: `venv/Scripts/python.exe -m pytest tests/ -q` (siempre acotado a `tests/`). Frontend: `npx tsc --noEmit`. Turnero: `npx vitest run`.
- **Línea base de TypeScript en `RRHH`: 27 errores preexistentes.** No agregar ninguno.
- **`node scripts/check-contrast.mjs` debe decir `Todos los pares cumplen AA.`** en `RRHH`.
- **DDL idempotente.** Patrón `IF COL_LENGTH(...) IS NULL` / `IF OBJECT_ID(...) IS NULL`, como `app/database/score_historico.py`.
- **Cero IDs de rol hardcodeados.** La autorización va por `require_permission(...)`.
- **Sin promedio compuesto.** La ficha muestra dimensiones separadas. Ninguna tarea debe introducir un único número que las resuma.
- **"Sin datos" nunca es cero.** Toda dimensión sin medición viaja como `None`/`null` y se muestra como texto, nunca como `0`.
- Los comentarios de código van **en castellano sin tildes**, siguiendo el estilo del repo.
- Los secretos van en `.env`, nunca hardcodeados ni commiteados.

---

## Contexto que el implementador necesita

**Por qué cambia el denominador.** El score sale de `AVG(eventos por sesión)` sobre `UsuarioAccesoLogs`. Eso premia entrar poco y quedarse: en la base de prueba, un empleado con 77 sesiones y 123 eventos puntúa 1.60, y otro con 3 sesiones y 11 eventos puntúa 3.67. El primero hizo 11 veces más y puntúa menos de la mitad. Dividir por horas efectivas trabajadas (que salen del reloj físico, independiente del sistema donde se generan los eventos) elimina ese incentivo.

**Por qué Turnero expone y RRHH consume.** `Turnero/lib/estadisticas/productividad.ts` ya calcula atendidos, válidas, breves, anomalías y desvío contra la mediana del propio trámite. Reimplementar eso en RRHH garantiza que las dos versiones se separen. Turnero es dueño de sus métricas.

**La trampa de `finalizado`.** `Turnero/server/jobs/abandonados.ts` marca `estado: "finalizado"` a los turnos que quedaron en `atendiendo` al cierre del día, agregando un `TurnoEvento` de tipo `revision`. Contar por `Turno.estado` acreditaría a los operadores trabajo que nadie hizo. **Siempre contar `TurnoEvento` con `tipo='finalizado' AND empleadoId IS NOT NULL`.**

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `Turnero/lib/estadisticas/rango-empleados.ts` (crear) | Arma las `AtencionEmpleado` de un rango de fechas, sin filtro de alcance. Sin HTTP |
| `Turnero/app/api/metricas/empleados/route.ts` (crear) | Expone `porEmpleado` por HTTP, autenticado con token de servicio |
| `Turnero/lib/auth/servicio.ts` (crear) | Valida el token de servicio de las llamadas máquina a máquina |
| `Backend_RRHH/app/services/turnero_client.py` (crear) | Cliente HTTP hacia Turnero. Traduce a un dataclass propio y tolera que no responda |
| `Backend_RRHH/app/routes/stats.py` (modificar) | Denominador nuevo del score; endpoint de la ficha |
| `Backend_RRHH/app/database/score_historico.py` (modificar) | Columna `formula` para versionar las corridas |
| `Backend_RRHH/app/services/merito.py` (crear) | Funciones puras: arma la ficha desde las dimensiones. Sin I/O |
| `Backend_RRHH/app/database/asistencia_merito.py` (crear) | Lee de `JornadaDiaria` la dimensión de cumplimiento por recurrencia |
| `Backend_RRHH/app/routes/employee.py` (modificar) | `position` valida contra el catálogo `Profession` |
| `RRHH/src/app/screens/Merito/Screen.tsx` (crear) | Pantalla de la ficha por gerencia |
| `RRHH/src/app/Componentes/Merito/TablaMerito.tsx` (crear) | Tabla comparativa de candidatos |
| `RRHH/src/app/Interfas/Interfaces.ts` (modificar) | Tipos de la ficha |

---

## Task 1: Versionar la fórmula en el historial

Antes de cambiar el cálculo hay que poder distinguir qué filas del historial salieron de qué fórmula. Si se cambia primero el cálculo, las corridas viejas y nuevas quedan mezcladas sin forma de separarlas.

**Files:**
- Modify: `app/database/score_historico.py`
- Test: `tests/test_score_historico_formula.py`

**Interfaces:**
- Produces: `FORMULA_ACTUAL: str`; `registrar_corrida` acepta `formula` en cada fila; `historial_empleado` devuelve `formula` en cada dict.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_score_historico_formula.py`:

```python
"""
Versionado de la formula en el historial de score.

El score cambia de denominador -de eventos por sesion a eventos por hora
efectiva-, asi que un numero viejo y uno nuevo no son comparables. Sin dejar
registrado con que formula se calculo cada corrida, la trayectoria de una
persona mostraria un salto que parece un cambio de desempeno y es un cambio
de unidad.
"""

from app.database.score_historico import FORMULA_ACTUAL, CREATE_TABLE_SQL, ALTER_FORMULA_SQL


def test_la_formula_actual_nombra_el_denominador():
    """El nombre tiene que decir que mide, no ser un numero de version."""
    assert "hora" in FORMULA_ACTUAL


def test_el_ddl_de_la_columna_es_idempotente():
    assert "IF COL_LENGTH('ScoreHistorico','formula') IS NULL" in ALTER_FORMULA_SQL


def test_la_tabla_se_crea_solo_si_no_existe():
    assert "IF OBJECT_ID('ScoreHistorico', 'U') IS NULL" in CREATE_TABLE_SQL
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_score_historico_formula.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'FORMULA_ACTUAL'`.

- [ ] **Step 3: Agregar la constante y el DDL**

En `app/database/score_historico.py`, después de `CREATE_INDEX_SQL`:

```python
# Nombre de la formula con la que se calculo una corrida. Queda guardado en
# cada fila porque el denominador cambio: un score viejo -promedio de eventos
# por sesion- y uno nuevo -eventos por hora efectiva- no son comparables entre
# si. Sin esto la trayectoria de una persona mostraria un salto que parece
# cambio de desempeno y es cambio de unidad.
FORMULA_ACTUAL = "eventos_por_hora_v1"

# Las corridas anteriores a este cambio quedan marcadas con el nombre viejo.
FORMULA_LEGADA = "eventos_por_sesion_v0"

ALTER_FORMULA_SQL = """
IF COL_LENGTH('ScoreHistorico','formula') IS NULL
ALTER TABLE ScoreHistorico ADD formula NVARCHAR(40) NULL;
"""

# Las filas que ya existen salieron todas de la formula vieja. Se las marca una
# sola vez; el WHERE formula IS NULL hace que repetirlo no toque nada.
MIGRAR_FORMULA_SQL = """
UPDATE ScoreHistorico SET formula = :legada WHERE formula IS NULL;
"""
```

- [ ] **Step 4: Correr el test para verificar que pasa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_score_historico_formula.py -v
```

Esperado: PASS, 3 tests.

- [ ] **Step 5: Ejecutar el DDL y la migración en `ensure_table`**

Reemplazar el cuerpo de `ensure_table` por:

```python
def ensure_table(db: Session) -> None:
    """Crea la tabla, su indice y la columna de formula. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.execute(text(CREATE_INDEX_SQL))
    db.execute(text(ALTER_FORMULA_SQL))
    db.commit()
    db.execute(text(MIGRAR_FORMULA_SQL), {"legada": FORMULA_LEGADA})
    db.commit()
```

- [ ] **Step 6: Persistir y devolver la formula**

En `registrar_corrida`, agregar `formula` al INSERT:

```python
    db.execute(
        text("""
            INSERT INTO ScoreHistorico
                (employeeId, score, metodoVinculo, idUsuario, sesiones, eventos,
                 esExento, ventanaMeses, formula)
            VALUES
                (:employeeId, :score, :metodoVinculo, :idUsuario, :sesiones,
                 :eventos, :esExento, :ventanaMeses, :formula)
        """),
        [
            {
                "employeeId": f["employeeId"],
                "score": f.get("score"),
                "metodoVinculo": f.get("metodoVinculo"),
                "idUsuario": f.get("idUsuario"),
                "sesiones": f.get("sesiones"),
                "eventos": f.get("eventos"),
                "esExento": 1 if f.get("esExento") else 0,
                "ventanaMeses": f.get("ventanaMeses", 12),
                "formula": f.get("formula", FORMULA_ACTUAL),
            }
            for f in filas
        ],
    )
```

Y en `historial_empleado`, agregar `formula` al SELECT:

```python
            SELECT TOP (:limite)
                   calculadoEn, score, metodoVinculo, idUsuario,
                   sesiones, eventos, esExento, ventanaMeses, formula
            FROM ScoreHistorico
            WHERE employeeId = :emp
            ORDER BY calculadoEn DESC
```

- [ ] **Step 7: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: todo verde, 369 tests (366 previos + 3 nuevos).

- [ ] **Step 8: Commit**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH
git add app/database/score_historico.py tests/test_score_historico_formula.py
git commit -m "feat(score): versionar la formula de calculo en el historial"
```

---

## Task 2: Cambiar el denominador a horas efectivas

**Files:**
- Modify: `app/routes/stats.py`
- Test: `tests/test_score_denominador.py`

**Interfaces:**
- Consumes: `FORMULA_ACTUAL` de Task 1.
- Produces: `horas_trabajadas_por_empleado(db, meses: int) -> dict[int, float]`; `score_por_hora(eventos: int | None, horas: float | None) -> float | None`; `calculate_productivity_scores` sigue devolviendo `dict[str, dict]` con las claves `score`, `sesiones`, `eventos`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_score_denominador.py`:

```python
"""
Denominador del score de productividad.

Hasta este cambio el score era el promedio de eventos por sesion, que premia
entrar poco y quedarse: en la base de prueba un empleado con 77 sesiones y 123
eventos puntuaba 1.60 y otro con 3 sesiones y 11 eventos puntuaba 3.67, o sea
que el que hizo 11 veces mas trabajo puntuaba menos de la mitad.

El denominador nuevo son las horas efectivamente trabajadas, que salen del
reloj fisico y por lo tanto no se pueden inflar desde el sistema donde se
generan los eventos.
"""

from app.routes.stats import score_por_hora


def test_mide_eventos_por_hora():
    assert score_por_hora(eventos=100, horas=50.0) == 2.0


def test_el_caso_que_motivo_el_cambio_se_da_vuelta():
    """
    Con el denominador viejo el de 123 eventos perdia contra el de 11. Con
    horas iguales, ahora gana el que hizo mas trabajo.
    """
    assert score_por_hora(123, 40.0) > score_por_hora(11, 40.0)


def test_sin_horas_no_hay_score():
    """
    Sin dato de asistencia no hay denominador, y dividir por cero o asumir una
    jornada inventaria el numero. Es "no medido", no cero.
    """
    assert score_por_hora(100, None) is None
    assert score_por_hora(100, 0.0) is None


def test_sin_eventos_pero_con_horas_es_cero_medido():
    """
    Distinto del anterior: la persona trabajo y no genero actividad en el
    sistema. Eso si es un cero real y se informa como tal.
    """
    assert score_por_hora(0, 40.0) == 0.0


def test_sin_eventos_ni_horas_no_hay_score():
    assert score_por_hora(None, None) is None


def test_redondea_a_dos_decimales():
    assert score_por_hora(10, 3.0) == 3.33
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_score_denominador.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'score_por_hora'`.

- [ ] **Step 3: Escribir la función pura**

En `app/routes/stats.py`, después de `asignar_scores`:

```python
def score_por_hora(eventos: int | None, horas: float | None) -> float | None:
    """
    Eventos registrados por hora efectivamente trabajada.

    Reemplaza al promedio de eventos por sesion, que premiaba entrar poco y
    quedarse: concentrar la misma actividad en menos sesiones subia el numero
    sin trabajar mas. Las horas salen del reloj fisico, asi que el denominador
    no se puede inflar desde el sistema donde se generan los eventos.

    Sin horas no hay score: dividir por cero o asumir una jornada seria
    inventar el numero. Con horas y sin eventos si hay un cero real -la
    persona trabajo y no genero actividad en este sistema-, que es distinto de
    no haber sido medida.

    Funcion pura, sin I/O.
    """
    if horas is None or horas <= 0:
        return None
    if eventos is None:
        return None
    return round(eventos / horas, 2)
```

- [ ] **Step 4: Correr el test para verificar que pasa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_score_denominador.py -v
```

Esperado: PASS, 6 tests.

- [ ] **Step 5: Leer las horas trabajadas de la base**

En `app/routes/stats.py`, después de `vincular_por_user_id`:

```python
def horas_trabajadas_por_empleado(db: Session, meses: int = VENTANA_MESES) -> dict[int, float]:
    """
    Horas efectivamente trabajadas por empleado en la ventana, desde el reloj.

    Es el denominador del score. Solo suma jornadas con horas cargadas: un dia
    sin marcaciones no aporta ni al numerador ni al denominador, asi que no
    diluye el resultado de quien falto con licencia.
    """
    filas = db.execute(text("""
        SELECT employeeId, SUM(horasTrabajadas) AS horas
        FROM JornadaDiaria
        WHERE fecha >= DATEADD(MONTH, -:meses, GETDATE())
          AND horasTrabajadas IS NOT NULL
        GROUP BY employeeId
    """), {"meses": meses}).mappings().all()
    return {int(f["employeeId"]): float(f["horas"]) for f in filas if f["horas"]}
```

- [ ] **Step 6: Usar el denominador nuevo en `sync_productivity_scores`**

En `sync_productivity_scores`, reemplazar el bloque que va desde `scores_por_empleado = asignar_scores(...)` hasta antes de `exentos = empleados_exentos(db)` por:

```python
    # El score medido ya no es el promedio de eventos por sesion que venia de
    # ObraSocial, sino los eventos totales sobre las horas del reloj. Por eso
    # se toma el conteo de eventos y se divide aca, en vez de usar el promedio
    # que calcula la consulta.
    horas = horas_trabajadas_por_empleado(db)
    eventos_por_empleado = {
        emp_id: (detalle_por_usuario.get(identidades.get(emp_id) or "") or {}).get("eventos")
        for emp_id in empleados
    }
    scores_por_empleado: dict[int, float | None] = {
        emp_id: score_por_hora(eventos_por_empleado.get(emp_id), horas.get(emp_id))
        for emp_id in empleados
    }
```

- [ ] **Step 7: Registrar la fórmula en la corrida**

En el mismo archivo, en el `registrar_corrida(...)` del final de `sync_productivity_scores`, agregar la clave `formula` al dict de cada fila, después de `"ventanaMeses": VENTANA_MESES,`:

```python
            "formula": FORMULA_ACTUAL,
```

Y agregar `FORMULA_ACTUAL` al import de `app.database.score_historico` en la cabecera del archivo:

```python
from app.database.score_historico import (
    FORMULA_ACTUAL,
    ensure_table as ensure_historico,
    historial_empleado,
    registrar_corrida,
)
```

- [ ] **Step 8: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: todo verde, 375 tests. Si `tests/test_score_vinculacion.py` falla, revisar que `asignar_scores` siga existiendo con su firma: se sigue usando para el mapa de identidades, aunque el score ya no salga de ahí.

- [ ] **Step 9: Verificar que la app importa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -c "import app.main; print('IMPORT OK')"
```

Esperado: `IMPORT OK`.

- [ ] **Step 10: Commit**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH
git add app/routes/stats.py tests/test_score_denominador.py
git commit -m "fix(score): medir eventos por hora efectiva en vez de por sesion"
```

---

## Task 3: Turnero expone su productividad

**Files:**
- Create: `Turnero/lib/auth/servicio.ts`
- Create: `Turnero/lib/estadisticas/rango-empleados.ts`
- Create: `Turnero/app/api/metricas/empleados/route.ts`
- Test: `Turnero/tests/servicio-token.test.ts`

**Interfaces:**
- Produces: `GET /api/metricas/empleados?desde=YYYY-MM-DD&hasta=YYYY-MM-DD` con header `Authorization: Bearer <token>`, que devuelve `{ empleados: [{ dniInstitucional, empleadoNombre, atendidos, validas, breves, anomalias, promedioSegundos, desvioContraMedianaSegundos, horasBox }] }`.
- Produces: `tokenDeServicioValido(header: string | null): boolean`.

- [ ] **Step 1: Escribir el test que falla**

Crear `Turnero/tests/servicio-token.test.ts`:

```typescript
import { describe, expect, it, beforeEach, afterEach } from "vitest"
import { tokenDeServicioValido } from "@/lib/auth/servicio"

const ORIGINAL = process.env.TURNERO_SERVICE_TOKEN

beforeEach(() => {
  process.env.TURNERO_SERVICE_TOKEN = "token-de-prueba"
})

afterEach(() => {
  process.env.TURNERO_SERVICE_TOKEN = ORIGINAL
})

describe("tokenDeServicioValido", () => {
  it("acepta el token configurado", () => {
    expect(tokenDeServicioValido("Bearer token-de-prueba")).toBe(true)
  })

  it("rechaza un token distinto", () => {
    expect(tokenDeServicioValido("Bearer otro")).toBe(false)
  })

  it("rechaza si falta el header", () => {
    expect(tokenDeServicioValido(null)).toBe(false)
  })

  it("rechaza si falta el prefijo Bearer", () => {
    expect(tokenDeServicioValido("token-de-prueba")).toBe(false)
  })

  it("rechaza todo si no hay token configurado", () => {
    // Sin secreto configurado el endpoint queda cerrado, nunca abierto: un
    // deploy al que se le olvido la variable no debe exponer el rendimiento
    // de cada operador a cualquiera.
    delete process.env.TURNERO_SERVICE_TOKEN
    expect(tokenDeServicioValido("Bearer token-de-prueba")).toBe(false)
  })
})
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Turnero && npx vitest run tests/servicio-token.test.ts
```

Esperado: FAIL con error de módulo no encontrado.

- [ ] **Step 3: Escribir el validador de token**

Crear `Turnero/lib/auth/servicio.ts`:

```typescript
/**
 * Autenticacion maquina a maquina para el endpoint de metricas.
 *
 * El endpoint expone el rendimiento individual de cada operador, asi que no
 * puede ser publico como /api/catalogo. Lo consume Backend_RRHH, que no tiene
 * sesion de usuario en Turnero: por eso un token de servicio compartido y no
 * el login de operador.
 */

/**
 * Sin TURNERO_SERVICE_TOKEN configurado devuelve false para todo. Cerrado por
 * omision: un deploy al que se le olvido la variable deja el endpoint mudo, no
 * abierto.
 */
export function tokenDeServicioValido(header: string | null): boolean {
  const esperado = process.env.TURNERO_SERVICE_TOKEN
  if (!esperado) return false
  if (!header) return false
  const prefijo = "Bearer "
  if (!header.startsWith(prefijo)) return false
  return header.slice(prefijo.length) === esperado
}
```

- [ ] **Step 4: Correr el test para verificar que pasa**

```bash
cd /c/Users/Emiliano/Documents/Turnero && npx vitest run tests/servicio-token.test.ts
```

Esperado: PASS, 5 tests.

- [ ] **Step 5: Armar las atenciones de un rango**

Crear `Turnero/lib/estadisticas/rango-empleados.ts`:

```typescript
import { prisma } from "@/lib/db"
import { calcularDuraciones } from "./duraciones"
import type { AtencionEmpleado } from "./productividad"

/**
 * Atenciones de todos los empleados en un rango, para el consumo de RRHH.
 *
 * A diferencia de las consultas del tablero no aplica alcance por tramite: el
 * consumidor es un sistema, no un supervisor, y del otro lado se decide quien
 * puede ver que.
 *
 * El empleado sale del evento `iniciado` y, si no lo hay, del `finalizado`:
 * son los dos que lleva un operador. El `generado` lo emite el kiosco y no
 * trae empleadoId.
 */
export async function atencionesDelRango(
  desde: Date,
  hasta: Date
): Promise<AtencionEmpleado[]> {
  const turnos = await prisma.turno.findMany({
    where: { fecha: { gte: desde, lte: hasta } },
    include: {
      tramite: { select: { duracionMinimaEsperada: true } },
      eventos: {
        select: { tipo: true, timestamp: true, empleadoId: true },
        orderBy: { timestamp: "asc" },
      },
    },
  })

  const nombres = new Map(
    (await prisma.empleado.findMany({ select: { id: true, nombre: true } })).map(
      (e) => [e.id, e.nombre]
    )
  )

  const atenciones: AtencionEmpleado[] = []

  for (const t of turnos) {
    const conEmpleado =
      t.eventos.find((e) => e.tipo === "iniciado" && e.empleadoId) ??
      t.eventos.find((e) => e.tipo === "finalizado" && e.empleadoId) ??
      null
    if (!conEmpleado?.empleadoId) continue

    const { atencionSegundos, clasificacion } = calcularDuraciones(
      t.eventos.map((e) => ({ tipo: e.tipo as never, timestamp: e.timestamp })),
      t.tramite.duracionMinimaEsperada
    )

    atenciones.push({
      empleadoId: conEmpleado.empleadoId,
      empleadoNombre: nombres.get(conEmpleado.empleadoId) ?? "",
      tramiteId: t.tramiteId,
      atencionSegundos,
      clasificacion,
    })
  }

  return atenciones
}

/**
 * Horas de box por empleado en el rango, como denominador de volumen.
 *
 * Una sesion sin `fin` es una que quedo abierta -el operador se fue sin
 * desloguear-. Se usa `ultimoLatido` en su lugar: contar hasta ahora le
 * regalaria horas que no estuvo.
 */
export async function horasDeBoxPorEmpleado(
  desde: Date,
  hasta: Date
): Promise<Map<string, number>> {
  const sesiones = await prisma.sesionOperador.findMany({
    where: { inicio: { gte: desde, lte: hasta } },
    select: { empleadoId: true, inicio: true, fin: true, ultimoLatido: true },
  })

  const horas = new Map<string, number>()
  for (const s of sesiones) {
    const cierre = s.fin ?? s.ultimoLatido
    const ms = cierre.getTime() - s.inicio.getTime()
    if (ms <= 0) continue
    horas.set(s.empleadoId, (horas.get(s.empleadoId) ?? 0) + ms / 3_600_000)
  }
  return horas
}
```

- [ ] **Step 6: Escribir el endpoint**

Crear `Turnero/app/api/metricas/empleados/route.ts`:

```typescript
import { NextResponse } from "next/server"
import { prisma } from "@/lib/db"
import { tokenDeServicioValido } from "@/lib/auth/servicio"
import { atencionesDelRango, horasDeBoxPorEmpleado } from "@/lib/estadisticas/rango-empleados"
import { porEmpleado } from "@/lib/estadisticas/productividad"

/**
 * Productividad por empleado para Backend_RRHH.
 *
 * Turnero es dueno de sus metricas: RRHH consume lo que se calcula aca en vez
 * de rehacer el calculo del otro lado, para que las dos versiones no se
 * separen con el tiempo.
 *
 * Se devuelve dniInstitucional y no el id interno porque es la clave con la
 * que RRHH vincula: es un identificador del mundo real y en Empleado es unico
 * y obligatorio.
 */
export async function GET(request: Request) {
  if (!tokenDeServicioValido(request.headers.get("authorization"))) {
    return NextResponse.json({ error: "No autorizado" }, { status: 401 })
  }

  const url = new URL(request.url)
  const desdeRaw = url.searchParams.get("desde")
  const hastaRaw = url.searchParams.get("hasta")
  if (!desdeRaw || !hastaRaw) {
    return NextResponse.json({ error: "Faltan desde y hasta" }, { status: 400 })
  }

  const desde = new Date(`${desdeRaw}T00:00:00.000Z`)
  const hasta = new Date(`${hastaRaw}T00:00:00.000Z`)
  if (Number.isNaN(desde.getTime()) || Number.isNaN(hasta.getTime())) {
    return NextResponse.json({ error: "Fechas invalidas" }, { status: 400 })
  }

  const atenciones = await atencionesDelRango(desde, hasta)
  const lineas = porEmpleado(atenciones)
  const horas = await horasDeBoxPorEmpleado(desde, hasta)

  const dnis = new Map(
    (await prisma.empleado.findMany({ select: { id: true, dniInstitucional: true } })).map(
      (e) => [e.id, e.dniInstitucional]
    )
  )

  return NextResponse.json({
    empleados: lineas
      .filter((l) => dnis.has(l.empleadoId))
      .map((l) => ({
        dniInstitucional: dnis.get(l.empleadoId),
        empleadoNombre: l.empleadoNombre,
        atendidos: l.atendidos,
        validas: l.validas,
        breves: l.breves,
        anomalias: l.anomalias,
        promedioSegundos: l.promedioSegundos,
        desvioContraMedianaSegundos: l.desvioContraMedianaSegundos,
        horasBox: Math.round((horas.get(l.empleadoId) ?? 0) * 100) / 100,
      })),
  })
}
```

- [ ] **Step 7: Documentar la variable de entorno**

En `Turnero/.env.example` (si no existe, crearlo), agregar:

```
# Token compartido con Backend_RRHH para GET /api/metricas/empleados.
# Sin este valor el endpoint responde 401 a todo.
TURNERO_SERVICE_TOKEN=
```

Y en `Turnero/.env` local, poner un valor real. **No commitear `.env`.**

- [ ] **Step 8: Correr la suite de Turnero**

```bash
cd /c/Users/Emiliano/Documents/Turnero && npx vitest run
```

Esperado: todo verde, con los 5 tests nuevos sumados al total previo.

- [ ] **Step 9: Verificar que compila**

```bash
cd /c/Users/Emiliano/Documents/Turnero && npx tsc --noEmit
```

Esperado: sin errores nuevos respecto de la línea base del repo.

- [ ] **Step 10: Commit**

```bash
cd /c/Users/Emiliano/Documents/Turnero
git add lib/auth/servicio.ts lib/estadisticas/rango-empleados.ts app/api/metricas/empleados/route.ts tests/servicio-token.test.ts .env.example
git commit -m "feat(metricas): endpoint de productividad por empleado para RRHH"
```

---

## Task 4: Cliente de Turnero en Backend_RRHH

**Files:**
- Create: `app/services/turnero_client.py`
- Test: `tests/test_turnero_client.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) MetricaTurnero` con `dniInstitucional: str`, `atendidos: int`, `validas: int`, `breves: int`, `anomalias: int`, `promedioSegundos: float | None`, `desvioContraMedianaSegundos: float | None`, `horasBox: float`; `parsear_metricas(payload: dict) -> dict[str, MetricaTurnero]`; `obtener_metricas(desde: date, hasta: date) -> dict[str, MetricaTurnero]`; `TURNERO_URL`, `TURNERO_TOKEN`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_turnero_client.py`:

```python
"""
Cliente HTTP hacia el endpoint de metricas de Turnero.

El parseo se testea puro, sin red: se le pasa el payload tal como lo devuelve
el endpoint y se verifica que se traduzca a los dataclasses propios. La llamada
HTTP en si no se testea aca -seria testear requests-, pero si se verifica que
un Turnero caido no rompa a RRHH.
"""

from app.services.turnero_client import MetricaTurnero, parsear_metricas

PAYLOAD = {
    "empleados": [
        {
            "dniInstitucional": "30111222",
            "empleadoNombre": "Ana Perez",
            "atendidos": 120,
            "validas": 100,
            "breves": 15,
            "anomalias": 5,
            "promedioSegundos": 480.0,
            "desvioContraMedianaSegundos": -30.0,
            "horasBox": 140.5,
        }
    ]
}


def test_indexa_por_dni():
    """El DNI es la clave de vinculo con Employee, no el id interno."""
    r = parsear_metricas(PAYLOAD)
    assert set(r.keys()) == {"30111222"}
    assert isinstance(r["30111222"], MetricaTurnero)


def test_traduce_los_campos():
    m = parsear_metricas(PAYLOAD)["30111222"]
    assert m.atendidos == 120
    assert m.validas == 100
    assert m.anomalias == 5
    assert m.horasBox == 140.5
    assert m.desvioContraMedianaSegundos == -30.0


def test_tolera_promedios_nulos():
    """Un empleado sin atenciones con tiempo devuelve null en los promedios."""
    payload = {"empleados": [{
        "dniInstitucional": "30111222", "empleadoNombre": "Ana",
        "atendidos": 0, "validas": 0, "breves": 0, "anomalias": 0,
        "promedioSegundos": None, "desvioContraMedianaSegundos": None,
        "horasBox": 0,
    }]}
    m = parsear_metricas(payload)["30111222"]
    assert m.promedioSegundos is None
    assert m.desvioContraMedianaSegundos is None


def test_un_payload_vacio_no_rompe():
    assert parsear_metricas({"empleados": []}) == {}
    assert parsear_metricas({}) == {}


def test_descarta_filas_sin_dni():
    """Sin DNI no hay con que vincular: la fila no sirve y se ignora."""
    payload = {"empleados": [
        {"dniInstitucional": None, "atendidos": 5, "validas": 5, "breves": 0,
         "anomalias": 0, "promedioSegundos": None,
         "desvioContraMedianaSegundos": None, "horasBox": 1},
    ]}
    assert parsear_metricas(payload) == {}
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_turnero_client.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.services.turnero_client'`.

- [ ] **Step 3: Escribir el cliente**

Crear `app/services/turnero_client.py`:

```python
"""
Cliente del endpoint de metricas de Turnero.

Turnero calcula su propia productividad -atendidos, validas, breves,
anomalias y desvio contra la mediana del tramite- y RRHH la consume en vez de
rehacerla: dos implementaciones de la misma metrica se separan con el tiempo y
despues nadie sabe cual es la buena.

Turnero es una fuente secundaria. Que no responda deja la dimension operativa
en "sin datos", nunca tumba la ficha ni la pantalla.
"""

import os
from dataclasses import dataclass
from datetime import date

import requests

TURNERO_URL = os.getenv("TURNERO_URL", "").rstrip("/")
TURNERO_TOKEN = os.getenv("TURNERO_SERVICE_TOKEN", "")
TIMEOUT_SEG = 10


@dataclass(frozen=True)
class MetricaTurnero:
    """Productividad de un operador en un rango, tal como la calcula Turnero."""
    dniInstitucional: str
    atendidos: int
    validas: int
    breves: int
    anomalias: int
    promedioSegundos: float | None
    desvioContraMedianaSegundos: float | None
    horasBox: float


def parsear_metricas(payload: dict) -> dict[str, MetricaTurnero]:
    """
    Traduce la respuesta del endpoint a un mapa por DNI.

    Se indexa por dniInstitucional y no por el id interno de Turnero porque el
    DNI es la clave con la que se vincula contra Employee: un identificador del
    mundo real, verificable, que no depende de como se creo cada cuenta.

    Funcion pura, sin I/O.
    """
    resultado: dict[str, MetricaTurnero] = {}
    for fila in payload.get("empleados", []):
        dni = fila.get("dniInstitucional")
        if not dni:
            continue
        resultado[str(dni).strip()] = MetricaTurnero(
            dniInstitucional=str(dni).strip(),
            atendidos=int(fila.get("atendidos") or 0),
            validas=int(fila.get("validas") or 0),
            breves=int(fila.get("breves") or 0),
            anomalias=int(fila.get("anomalias") or 0),
            promedioSegundos=fila.get("promedioSegundos"),
            desvioContraMedianaSegundos=fila.get("desvioContraMedianaSegundos"),
            horasBox=float(fila.get("horasBox") or 0),
        )
    return resultado


def obtener_metricas(desde: date, hasta: date) -> dict[str, MetricaTurnero]:
    """
    Pide las metricas del rango. Devuelve {} si Turnero no esta disponible.

    El {} no se distingue de "nadie atendio nada", y esta bien: en los dos
    casos la ficha muestra la dimension operativa como sin datos, que es lo
    honesto. Lo que no puede pasar es que la pantalla se caiga porque una
    fuente secundaria no respondio.
    """
    if not TURNERO_URL or not TURNERO_TOKEN:
        return {}
    try:
        resp = requests.get(
            f"{TURNERO_URL}/api/metricas/empleados",
            params={"desde": desde.isoformat(), "hasta": hasta.isoformat()},
            headers={"Authorization": f"Bearer {TURNERO_TOKEN}"},
            timeout=TIMEOUT_SEG,
        )
        resp.raise_for_status()
        return parsear_metricas(resp.json())
    except Exception as e:
        print(f"Aviso: no se pudieron traer las metricas de Turnero: {e}")
        return {}
```

- [ ] **Step 4: Correr el test para verificar que pasa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_turnero_client.py -v
```

Esperado: PASS, 5 tests.

- [ ] **Step 5: Documentar las variables de entorno**

En `Backend_RRHH/.env`, agregar (con el mismo valor de token que se puso en `Turnero/.env`):

```
TURNERO_URL=http://localhost:3001
TURNERO_SERVICE_TOKEN=
```

**No commitear `.env`.** Verificar que ya esté en `.gitignore`:

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && grep -n "^\.env$" .gitignore
```

Esperado: una línea con `.env`. Si no aparece, agregarla antes de seguir.

- [ ] **Step 6: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: todo verde, 380 tests.

- [ ] **Step 7: Commit**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH
git add app/services/turnero_client.py tests/test_turnero_client.py
git commit -m "feat(turnero): cliente de las metricas de productividad"
```

---

## Task 5: Dimensión de cumplimiento desde asistencia

**Files:**
- Create: `app/database/asistencia_merito.py`
- Test: `tests/test_asistencia_merito.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) Cumplimiento` con `diasTrabajados: int`, `diasConAbuso: int`, `tasaAbuso: float | None`; `cumplimiento_por_empleado(db, meses: int) -> dict[int, Cumplimiento]`; `tasa_abuso(dias_con_abuso: int, dias_trabajados: int) -> float | None`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_asistencia_merito.py`:

```python
"""
Dimension de cumplimiento para la ficha de merito.

Se mide por recurrencia y no por minutos acumulados: sumar minutos castiga
igual un accidente de transito puntual que un patron cronico, y el primero no
dice nada del desempeno. El motor de asistencia ya calcula la senal correcta
-el flag abusoEntrada, que marca a quien se recuesta sistematicamente sobre el
margen de tolerancia sin excederlo-, asi que aca solo se la agrega.
"""

from app.database.asistencia_merito import tasa_abuso


def test_la_tasa_es_dias_con_abuso_sobre_trabajados():
    assert tasa_abuso(dias_con_abuso=15, dias_trabajados=60) == 0.25


def test_sin_dias_trabajados_no_hay_tasa():
    """No se lo midio; no es un cumplimiento perfecto."""
    assert tasa_abuso(0, 0) is None


def test_cero_abusos_es_cero_medido():
    assert tasa_abuso(0, 60) == 0.0


def test_redondea_a_dos_decimales():
    assert tasa_abuso(1, 3) == 0.33
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_asistencia_merito.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.database.asistencia_merito'`.

- [ ] **Step 3: Escribir el módulo**

Crear `app/database/asistencia_merito.py`:

```python
"""
Cumplimiento horario como dimension de la ficha de merito.

Se mide por recurrencia, no por minutos acumulados: sumar minutos castiga
igual una demora puntual que un patron sostenido, y solo el segundo dice algo
del desempeno. El motor de asistencia ya calcula la senal correcta en el flag
abusoEntrada -quien se recuesta sistematicamente sobre el margen de tolerancia
sin llegar a excederlo-, asi que aca solo se agrega sobre los dias trabajados.

Es la unica dimension comparable entre todas las funciones por igual: no
depende de que el trabajo de la persona pase por ningun sistema.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Cumplimiento:
    diasTrabajados: int
    diasConAbuso: int
    tasaAbuso: float | None


def tasa_abuso(dias_con_abuso: int, dias_trabajados: int) -> float | None:
    """
    Proporcion de dias con abuso de tolerancia sobre los dias trabajados.

    Sin dias trabajados no hay tasa: seria dividir por cero, y devolver 0.0
    diria "cumplimiento perfecto" de alguien a quien no se midio.

    Funcion pura, sin I/O.
    """
    if dias_trabajados <= 0:
        return None
    return round(dias_con_abuso / dias_trabajados, 2)


def cumplimiento_por_empleado(db: Session, meses: int = 12) -> dict[int, Cumplimiento]:
    """
    Dias trabajados y dias con abuso de entrada por empleado, en la ventana.

    Solo cuenta jornadas con horas cargadas: un dia de licencia no es un dia
    trabajado y no debe engrosar el denominador, porque bajaria artificialmente
    la tasa de quien estuvo ausente con derecho.
    """
    filas = db.execute(text("""
        SELECT employeeId,
               COUNT(*) AS dias,
               SUM(CASE WHEN abusoEntrada = 1 THEN 1 ELSE 0 END) AS abusos
        FROM JornadaDiaria
        WHERE fecha >= DATEADD(MONTH, -:meses, GETDATE())
          AND horasTrabajadas IS NOT NULL
          AND horasTrabajadas > 0
        GROUP BY employeeId
    """), {"meses": meses}).mappings().all()

    return {
        int(f["employeeId"]): Cumplimiento(
            diasTrabajados=int(f["dias"]),
            diasConAbuso=int(f["abusos"] or 0),
            tasaAbuso=tasa_abuso(int(f["abusos"] or 0), int(f["dias"])),
        )
        for f in filas
    }
```

- [ ] **Step 4: Correr el test para verificar que pasa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_asistencia_merito.py -v
```

Esperado: PASS, 4 tests.

- [ ] **Step 5: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: todo verde, 384 tests.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH
git add app/database/asistencia_merito.py tests/test_asistencia_merito.py
git commit -m "feat(merito): cumplimiento horario por recurrencia de abuso"
```

---

## Task 6: Armado de la ficha

**Files:**
- Create: `app/services/merito.py`
- Test: `tests/test_merito.py`

**Interfaces:**
- Consumes: `Cumplimiento` de Task 5; `MetricaTurnero` de Task 4; `PuntajeFeedback` de `app/services/feedback_score.py` (campos `promedio: float | None`, `evaluadores: int`, `suficiente: bool`).
- Produces: `@dataclass(frozen=True) DimensionMerito` con `valor: float | None`, `detalle: str`, `medida: bool`; `@dataclass(frozen=True) FichaMerito` con `employeeId: int`, `nombre: str`, `position: str | None`, `cumplimiento: DimensionMerito`, `actividad: DimensionMerito`, `operativo: DimensionMerito`, `feedback: DimensionMerito`, `trayectoria: str`, `cobertura: int`, `dimensionesTotales: int`; `armar_ficha(...) -> FichaMerito`; `describir_trayectoria(historial: list[float | None]) -> str`; `DIMENSIONES_TOTALES: int`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_merito.py`:

```python
"""
Armado de la ficha de merito por persona.

Funciones puras: reciben las dimensiones ya calculadas y deciden que se
muestra y que se marca como sin datos. No componen un promedio a proposito -un
ascenso se decide entre dos y cinco candidatos, y ahi un numero unico no agrega
informacion: esconde la que hay-.
"""

from app.database.asistencia_merito import Cumplimiento
from app.services.feedback_score import PuntajeFeedback
from app.services.merito import (
    DIMENSIONES_TOTALES,
    armar_ficha,
    describir_trayectoria,
)
from app.services.turnero_client import MetricaTurnero


def _cumpl(dias=60, abusos=3):
    return Cumplimiento(diasTrabajados=dias, diasConAbuso=abusos,
                        tasaAbuso=round(abusos / dias, 2) if dias else None)


def _turnero(validas=100, atendidos=120):
    return MetricaTurnero(
        dniInstitucional="30111222", atendidos=atendidos, validas=validas,
        breves=15, anomalias=5, promedioSegundos=480.0,
        desvioContraMedianaSegundos=-30.0, horasBox=140.0,
    )


# -- Que se muestra y que no ---------------------------------------------------

def test_una_dimension_sin_dato_se_marca_no_medida():
    f = armar_ficha(
        employee_id=1, nombre="Ana", position="Analista",
        cumplimiento=None, actividad=None, turnero=None,
        feedback=PuntajeFeedback(promedio=None, evaluadores=1, suficiente=False),
        historial=[],
    )
    assert f.cumplimiento.medida is False
    assert f.cumplimiento.valor is None
    assert f.feedback.medida is False


def test_la_ficha_no_devuelve_un_promedio_compuesto():
    """
    El ascenso se decide entre pocos candidatos leyendo la evidencia. Un numero
    unico no agrega informacion, esconde de donde sale.
    """
    f = armar_ficha(
        employee_id=1, nombre="Ana", position=None,
        cumplimiento=_cumpl(), actividad=4.2, turnero=_turnero(),
        feedback=PuntajeFeedback(promedio=8.0, evaluadores=5, suficiente=True),
        historial=[4.0, 4.1, 4.2],
    )
    assert not hasattr(f, "total")
    assert not hasattr(f, "promedio")
    assert not hasattr(f, "scoreFinal")


def test_la_cobertura_cuenta_las_dimensiones_medidas():
    f = armar_ficha(
        employee_id=1, nombre="Ana", position=None,
        cumplimiento=_cumpl(), actividad=4.2, turnero=None,
        feedback=PuntajeFeedback(promedio=None, evaluadores=2, suficiente=False),
        historial=[],
    )
    assert f.cobertura == 2
    assert f.dimensionesTotales == DIMENSIONES_TOTALES


def test_el_feedback_insuficiente_no_expone_el_promedio():
    """
    Con menos de 3 evaluadores el motor devuelve promedio None; la ficha no
    debe inventarlo ni mostrar el conteo como si fuera un puntaje.
    """
    f = armar_ficha(
        employee_id=1, nombre="Ana", position=None,
        cumplimiento=None, actividad=None, turnero=None,
        feedback=PuntajeFeedback(promedio=None, evaluadores=2, suficiente=False),
        historial=[],
    )
    assert f.feedback.valor is None
    assert "2" in f.feedback.detalle


def test_el_cumplimiento_informa_la_recurrencia_no_los_minutos():
    f = armar_ficha(
        employee_id=1, nombre="Ana", position=None,
        cumplimiento=_cumpl(dias=60, abusos=15), actividad=None, turnero=None,
        feedback=PuntajeFeedback(promedio=None, evaluadores=0, suficiente=False),
        historial=[],
    )
    assert f.cumplimiento.valor == 0.25
    assert "15" in f.cumplimiento.detalle and "60" in f.cumplimiento.detalle


def test_el_operativo_usa_las_validas_no_los_atendidos():
    """
    `atendidos` incluye breves y anomalias, que son justamente las atenciones
    de plausibilidad dudosa. La dimension se apoya en las validas.
    """
    f = armar_ficha(
        employee_id=1, nombre="Ana", position=None,
        cumplimiento=None, actividad=None, turnero=_turnero(validas=100, atendidos=120),
        feedback=PuntajeFeedback(promedio=None, evaluadores=0, suficiente=False),
        historial=[],
    )
    assert f.operativo.valor == 100
    assert "120" in f.operativo.detalle


# -- Trayectoria ---------------------------------------------------------------

def test_sin_historial_suficiente_no_se_describe_tendencia():
    assert describir_trayectoria([]) == "sin historial"
    assert describir_trayectoria([4.0]) == "sin historial"


def test_una_subida_sostenida_se_describe_como_mejora():
    assert describir_trayectoria([3.0, 3.5, 4.2]) == "mejorando"


def test_una_caida_sostenida_se_describe_como_baja():
    assert describir_trayectoria([4.2, 3.5, 3.0]) == "bajando"


def test_una_variacion_chica_se_considera_estable():
    assert describir_trayectoria([4.0, 4.05, 3.98]) == "sostenida"


def test_los_periodos_sin_medicion_no_cuentan_como_caida():
    """
    Un None en el historial es "no se lo midio", no un cero. Tratarlo como cero
    dibujaria una caida que nunca ocurrio.
    """
    assert describir_trayectoria([4.0, None, 4.1]) == "sostenida"
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_merito.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.services.merito'`.

- [ ] **Step 3: Escribir el servicio**

Crear `app/services/merito.py`:

```python
"""
Ficha de merito por persona.

Un ascenso se decide entre dos y cinco candidatos, unas pocas veces al ano, y
es caro de errar. En ese regimen un numero compuesto no agrega informacion:
con cinco filas la autoridad puede leer la evidencia directamente, y el
promedio unico solo esconde de donde sale.

Por eso esta ficha NO devuelve un total. Devuelve cada dimension por separado,
cada una con su detalle en palabras y con si esta medida o no, mas cuantas de
las cuatro tienen dato. Que una persona destaque con cobertura 2 de 4 es
informacion que la autoridad necesita, no un defecto a esconder.

Funciones puras: no tocan la base ni la red.
"""

from dataclasses import dataclass

from app.database.asistencia_merito import Cumplimiento
from app.services.feedback_score import PuntajeFeedback
from app.services.turnero_client import MetricaTurnero

# Cumplimiento, actividad en el sistema, volumen operativo y feedback.
DIMENSIONES_TOTALES = 4

# Cuanto tiene que moverse la trayectoria para no considerarse estable. Por
# debajo de esto la variacion es ruido de medicion, no un cambio real.
UMBRAL_TENDENCIA = 0.15


@dataclass(frozen=True)
class DimensionMerito:
    """Una dimension de la ficha. `medida` distingue el cero del sin dato."""
    valor: float | None
    detalle: str
    medida: bool


@dataclass(frozen=True)
class FichaMerito:
    employeeId: int
    nombre: str
    position: str | None
    cumplimiento: DimensionMerito
    actividad: DimensionMerito
    operativo: DimensionMerito
    feedback: DimensionMerito
    trayectoria: str
    cobertura: int
    dimensionesTotales: int


_SIN_DATO = "sin datos"


def describir_trayectoria(historial: list[float | None]) -> str:
    """
    Como viene evolucionando la persona respecto de si misma.

    Es la unica comparacion que se sostiene con pocos datos: no depende de que
    haya companeros comparables ni de que el grupo tenga masa estadistica, asi
    que sirve igual para quien esta solo en su funcion.

    Los None se descartan: son periodos sin medicion, y tratarlos como cero
    dibujaria una caida que nunca ocurrio.
    """
    medidos = [v for v in historial if v is not None]
    if len(medidos) < 2:
        return "sin historial"

    delta = medidos[-1] - medidos[0]
    if delta > UMBRAL_TENDENCIA:
        return "mejorando"
    if delta < -UMBRAL_TENDENCIA:
        return "bajando"
    return "sostenida"


def _dim_cumplimiento(c: Cumplimiento | None) -> DimensionMerito:
    if c is None or c.tasaAbuso is None:
        return DimensionMerito(None, _SIN_DATO, False)
    return DimensionMerito(
        valor=c.tasaAbuso,
        detalle=f"{c.diasConAbuso} de {c.diasTrabajados} días con abuso de tolerancia",
        medida=True,
    )


def _dim_actividad(score: float | None) -> DimensionMerito:
    if score is None:
        return DimensionMerito(None, _SIN_DATO, False)
    return DimensionMerito(
        valor=score,
        detalle=f"{score} eventos por hora trabajada",
        medida=True,
    )


def _dim_operativo(m: MetricaTurnero | None) -> DimensionMerito:
    if m is None:
        return DimensionMerito(None, _SIN_DATO, False)
    # Se informan las validas y no los atendidos: `atendidos` incluye las
    # breves y las anomalias, que son las atenciones de plausibilidad dudosa.
    return DimensionMerito(
        valor=float(m.validas),
        detalle=f"{m.validas} atenciones válidas de {m.atendidos}, {m.horasBox} h de box",
        medida=True,
    )


def _dim_feedback(p: PuntajeFeedback) -> DimensionMerito:
    if not p.suficiente or p.promedio is None:
        return DimensionMerito(
            valor=None,
            detalle=f"{p.evaluadores} evaluadores, hacen falta 3",
            medida=False,
        )
    return DimensionMerito(
        valor=p.promedio,
        detalle=f"{p.promedio} sobre 5, {p.evaluadores} evaluadores",
        medida=True,
    )


def armar_ficha(
    employee_id: int,
    nombre: str,
    position: str | None,
    cumplimiento: Cumplimiento | None,
    actividad: float | None,
    turnero: MetricaTurnero | None,
    feedback: PuntajeFeedback,
    historial: list[float | None],
) -> FichaMerito:
    """Arma la ficha de una persona. No compone ningun total."""
    dims = (
        _dim_cumplimiento(cumplimiento),
        _dim_actividad(actividad),
        _dim_operativo(turnero),
        _dim_feedback(feedback),
    )
    return FichaMerito(
        employeeId=employee_id,
        nombre=nombre,
        position=position,
        cumplimiento=dims[0],
        actividad=dims[1],
        operativo=dims[2],
        feedback=dims[3],
        trayectoria=describir_trayectoria(historial),
        cobertura=sum(1 for d in dims if d.medida),
        dimensionesTotales=DIMENSIONES_TOTALES,
    )
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_merito.py -v
```

Esperado: PASS, 12 tests.

- [ ] **Step 5: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: todo verde, 396 tests.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH
git add app/services/merito.py tests/test_merito.py
git commit -m "feat(merito): armado de la ficha por dimensiones sin total compuesto"
```

---

## Task 7: Endpoint de la ficha por gerencia

**Files:**
- Modify: `app/routes/stats.py`
- Test: `tests/test_merito_endpoint.py`

**Interfaces:**
- Consumes: `armar_ficha`, `FichaMerito` de Task 6; `cumplimiento_por_empleado` de Task 5; `obtener_metricas` de Task 4; `cargar_respuestas_normalizadas`, `puntaje_feedback` de `app/routes/feedback.py` y `app/services/feedback_score.py`.
- Produces: `GET /stats/merito/{department_id}`; `serie_historica(db, employee_id, limite) -> list[float | None]`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_merito_endpoint.py`:

```python
"""
Endpoint de la ficha de merito por gerencia.

El handler se invoca directamente, sin servidor HTTP, siguiendo el patron de
tests/test_feedback_endpoints.py.
"""

from app.routes.stats import serie_historica
from tests.fakes import FakeSession

FRAG_HIST = "FROM ScoreHistorico"


def test_la_serie_va_de_la_mas_vieja_a_la_mas_nueva():
    """
    describir_trayectoria compara el primero contra el ultimo, asi que la serie
    tiene que llegarle en orden cronologico. La consulta trae al reves -la mas
    reciente primero- para poder usar TOP.
    """
    db = FakeSession({FRAG_HIST: [
        {"score": 4.2}, {"score": 4.0}, {"score": 3.5},
    ]})
    assert serie_historica(db, 1, 3) == [3.5, 4.0, 4.2]


def test_conserva_los_periodos_sin_medicion():
    """Un None es informacion: hubo corrida y no se la pudo medir."""
    db = FakeSession({FRAG_HIST: [{"score": 4.2}, {"score": None}]})
    assert serie_historica(db, 1, 2) == [None, 4.2]


def test_sin_historial_devuelve_lista_vacia():
    db = FakeSession({FRAG_HIST: []})
    assert serie_historica(db, 1, 5) == []
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_merito_endpoint.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'serie_historica'`.

- [ ] **Step 3: Escribir la serie histórica**

En `app/routes/stats.py`, después de `metodos_vinculo`:

```python
def serie_historica(db: Session, employee_id: int, limite: int = 6) -> list[float | None]:
    """
    Ultimos scores de una persona, del mas viejo al mas nuevo.

    La consulta ordena descendente para poder usar TOP, y el resultado se
    invierte: describir_trayectoria compara el primer valor contra el ultimo y
    necesita orden cronologico.

    Los None se conservan: son corridas en las que hubo calculo y no se pudo
    medir, que es distinto de no haber corrido.
    """
    filas = db.execute(text("""
        SELECT TOP (:limite) score
        FROM ScoreHistorico
        WHERE employeeId = :emp
        ORDER BY calculadoEn DESC
    """), {"emp": employee_id, "limite": limite}).mappings().all()
    return [float(f["score"]) if f["score"] is not None else None for f in reversed(filas)]
```

- [ ] **Step 4: Correr el test para verificar que pasa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_merito_endpoint.py -v
```

Esperado: PASS, 3 tests.

- [ ] **Step 5: Agregar los imports**

En la cabecera de `app/routes/stats.py`, junto a los imports existentes:

```python
from datetime import date, timedelta

from app.database.asistencia_merito import cumplimiento_por_empleado
from app.routes.feedback import cargar_respuestas_normalizadas
from app.database.feedback_config import get_periodo_actual
from app.services.feedback_score import puntaje_feedback
from app.services.merito import armar_ficha
from app.services.turnero_client import obtener_metricas
```

- [ ] **Step 6: Escribir el endpoint**

Al final de `app/routes/stats.py`:

```python
@router.get("/merito/{department_id}", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def get_merito_gerencia(department_id: int, db: Session = Depends(get_db)):
    """
    Ficha comparativa de las personas de una gerencia, para decidir un ascenso.

    El universo es la gerencia y no toda la nomina a proposito: comparar un
    administrativo con alguien de ventanilla no dice nada, y era el defecto que
    tenia el ranking global.

    No devuelve un puntaje compuesto. Cada dimension viaja por separado con su
    detalle y con si esta medida, mas la cobertura, para que quien decide vea
    tambien cuanta evidencia tiene detras de cada persona.
    """
    ensure_historico(db)

    empleados = db.execute(text("""
        SELECT e.id, e.name, e.dni, c.position
        FROM Employee e
        LEFT JOIN CondicionLaboral c ON c.employeeId = e.id
        WHERE e.departmentId = :dep
        ORDER BY e.name
    """), {"dep": department_id}).mappings().all()

    if not empleados:
        return {"success": True, "data": {"departmentId": department_id, "fichas": []}}

    cumplimientos = cumplimiento_por_empleado(db, VENTANA_MESES)
    hasta = date.today()
    desde = hasta - timedelta(days=30 * VENTANA_MESES)
    metricas = obtener_metricas(desde, hasta)

    periodo = get_periodo_actual(db)
    respuestas = cargar_respuestas_normalizadas(db, periodo)

    scores = {
        int(r["id"]): (float(r["productivityScore"]) if r["productivityScore"] is not None else None)
        for r in db.execute(text(
            "SELECT id, productivityScore FROM Employee WHERE departmentId = :dep"
        ), {"dep": department_id}).mappings().all()
    }

    fichas = []
    for emp in empleados:
        emp_id = int(emp["id"])
        dni = (emp["dni"] or "").strip()
        ficha = armar_ficha(
            employee_id=emp_id,
            nombre=emp["name"],
            position=emp["position"],
            cumplimiento=cumplimientos.get(emp_id),
            actividad=scores.get(emp_id),
            turnero=metricas.get(dni),
            feedback=puntaje_feedback(respuestas.get(emp_id, [])),
            historial=serie_historica(db, emp_id),
        )
        fichas.append({
            "employeeId": ficha.employeeId,
            "nombre": ficha.nombre,
            "position": ficha.position,
            "cumplimiento": vars(ficha.cumplimiento),
            "actividad": vars(ficha.actividad),
            "operativo": vars(ficha.operativo),
            "feedback": vars(ficha.feedback),
            "trayectoria": ficha.trayectoria,
            "cobertura": ficha.cobertura,
            "dimensionesTotales": ficha.dimensionesTotales,
        })

    return {"success": True, "data": {"departmentId": department_id, "fichas": fichas}}
```

- [ ] **Step 7: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: todo verde, 399 tests.

- [ ] **Step 8: Verificar que la app importa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -c "import app.main; print('IMPORT OK')"
```

Esperado: `IMPORT OK`. Si aparece un `ImportError` circular entre `stats.py` y `feedback.py`, mover el import de `cargar_respuestas_normalizadas` adentro de la función `get_merito_gerencia`.

- [ ] **Step 9: Commit**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH
git add app/routes/stats.py tests/test_merito_endpoint.py
git commit -m "feat(merito): endpoint de la ficha por gerencia"
```

---

## Task 8: Conectar el selector de cargo al catálogo

**Files:**
- Modify: `app/routes/rrhh.py:430`
- Test: `tests/test_position_catalogo.py`

**Dónde se escribe `position`.** Hay un solo punto en todo el backend: `app/routes/rrhh.py`, en el handler que guarda la condición laboral. La línea `position = data.get("position") or None` alimenta tanto la rama del `UPDATE` como la del `INSERT`, así que validar ahí cubre los dos casos. `app/routes/employee.py` **lee** `CondicionLaboral.position` (líneas 78 y 412) pero nunca lo escribe; su único `INSERT ... position` es a `WorkExperience`, que es experiencia laboral previa y no el cargo actual — no tocarlo.

**Interfaces:**
- Produces: `position_valida(position: str | None, catalogo: set[str]) -> bool`; `cargos_activos(db) -> set[str]`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_position_catalogo.py`:

```python
"""
El cargo del empleado tiene que salir del catalogo, no ser texto libre.

Existe el modulo Configuracion -> "Catalogo de Profesiones y Cargos", que
escribe en la tabla Profession, pero CondicionLaboral.position es una columna
de texto sin relacion con el: hoy guarda lo que sea que llegue. Con texto libre
"Analista" y "analista Sr." son cargos distintos, y cualquier agrupacion por
funcion se rompe en silencio.
"""

from app.routes.rrhh import position_valida

CATALOGO = {"Analista", "Gerente", "Administración Pública"}


def test_acepta_un_cargo_del_catalogo():
    assert position_valida("Analista", CATALOGO) is True


def test_rechaza_un_cargo_que_no_existe():
    assert position_valida("Analista Sr.", CATALOGO) is False


def test_ignora_espacios_al_comparar():
    assert position_valida("  Analista  ", CATALOGO) is True


def test_vacio_es_valido():
    """No cargar el cargo es legitimo; inventarlo no."""
    assert position_valida(None, CATALOGO) is True
    assert position_valida("", CATALOGO) is True


def test_con_catalogo_vacio_no_se_bloquea_la_carga():
    """
    Si nadie cargo el catalogo todavia, exigirlo dejaria el alta de empleados
    inutilizable. Se acepta y queda para normalizar despues.
    """
    assert position_valida("Cualquiera", set()) is True
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_position_catalogo.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'position_valida'`.

- [ ] **Step 3: Escribir la validación**

En `app/routes/rrhh.py`, después de los imports:

```python
def cargos_activos(db: Session) -> set[str]:
    """Nombres del catalogo de Profesiones y Cargos que estan activos."""
    filas = db.execute(text("SELECT nombre FROM Profession WHERE activo = 1")).mappings().all()
    return {str(f["nombre"]).strip() for f in filas}


def position_valida(position: str | None, catalogo: set[str]) -> bool:
    """
    El cargo tiene que estar en el catalogo, o estar vacio.

    No cargar el cargo es legitimo; inventar uno que no existe no, porque
    despues "Analista" y "analista Sr." quedan como funciones distintas y
    cualquier agrupacion por funcion se rompe sin que nadie lo note.

    Con el catalogo vacio se acepta todo: exigirlo antes de que alguien lo
    cargue dejaria el alta de empleados inutilizable.

    Funcion pura, sin I/O.
    """
    if not position or not position.strip():
        return True
    if not catalogo:
        return True
    return position.strip() in catalogo
```

- [ ] **Step 4: Correr el test para verificar que pasa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_position_catalogo.py -v
```

Esperado: PASS, 5 tests.

- [ ] **Step 5: Aplicar la validación al guardar**

En `app/routes/rrhh.py`, la línea 430 dice:

```python
    position = data.get("position") or None
```

Insertar inmediatamente debajo:

```python
    # El cargo tiene que venir del catalogo de Configuracion -> Profesiones y
    # Cargos. Con texto libre, "Analista" y "analista Sr." quedan como
    # funciones distintas y la comparacion por funcion se rompe en silencio.
    if not position_valida(position, cargos_activos(db)):
        raise HTTPException(
            status_code=400,
            detail="El cargo debe existir en Configuración → Profesiones y Cargos.",
        )
```

Queda antes de las dos ramas (`UPDATE` e `INSERT`), así que cubre los dos casos con una sola guarda.

- [ ] **Step 6: Verificar que los imports necesarios ya están**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && grep -n "^from fastapi import\|^from sqlalchemy import\|^from sqlalchemy.orm import" app/routes/rrhh.py
```

Esperado: `HTTPException` en el import de fastapi, `text` en el de sqlalchemy y `Session` en el de sqlalchemy.orm. Si falta alguno, agregarlo antes de seguir.

- [ ] **Step 7: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: todo verde, 404 tests.

- [ ] **Step 8: Verificar que la app importa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -c "import app.main; print('IMPORT OK')"
```

Esperado: `IMPORT OK`.

- [ ] **Step 9: Commit**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH
git add app/routes/rrhh.py tests/test_position_catalogo.py
git commit -m "fix(rrhh): validar el cargo contra el catalogo de Profesiones"
```

---

## Task 9: Pantalla de la ficha en el frontend

**Files:**
- Modify: `RRHH/src/app/Interfas/Interfaces.ts`
- Create: `RRHH/src/app/Componentes/Merito/TablaMerito.tsx`
- Create: `RRHH/src/app/screens/Merito/Screen.tsx`

**Interfaces:**
- Consumes: `GET /stats/merito/{department_id}` de Task 7.

- [ ] **Step 1: Agregar los tipos**

En `RRHH/src/app/Interfas/Interfaces.ts`, al final del archivo:

```typescript
/** Una dimensión de la ficha de mérito. `medida` distingue el cero del sin dato. */
export interface DimensionMerito {
  valor: number | null;
  detalle: string;
  medida: boolean;
}

export interface FichaMerito {
  employeeId: number;
  nombre: string;
  position: string | null;
  cumplimiento: DimensionMerito;
  actividad: DimensionMerito;
  operativo: DimensionMerito;
  feedback: DimensionMerito;
  trayectoria: string;
  cobertura: number;
  dimensionesTotales: number;
}
```

- [ ] **Step 2: Escribir la tabla**

Crear `RRHH/src/app/Componentes/Merito/TablaMerito.tsx`:

```tsx
"use client";

// Ficha comparativa para decidir un ascenso dentro de una gerencia.
//
// No hay columna de puntaje total, y es deliberado: un ascenso se decide entre
// pocos candidatos, y ahi un numero unico no agrega informacion sobre lo que ya
// muestran las columnas -esconde de donde sale-. La autoridad compara la
// evidencia; el sistema no emite veredicto.

import { AlertTriangle, Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { DimensionMerito, FichaMerito } from "@/app/Interfas/Interfaces";

function Celda({ dim }: { dim: DimensionMerito }) {
  if (!dim.medida) {
    return (
      <div className="text-sm text-muted-foreground italic" title={dim.detalle}>
        Sin datos
      </div>
    );
  }
  return (
    <div>
      <span className="font-semibold text-foreground tabular-nums">{dim.valor}</span>
      <p className="text-xs text-muted-foreground">{dim.detalle}</p>
    </div>
  );
}

function Trayectoria({ valor }: { valor: string }) {
  const iconos: Record<string, React.ReactNode> = {
    mejorando: <TrendingUp size={16} className="text-success" aria-hidden="true" />,
    bajando: <TrendingDown size={16} className="text-error" aria-hidden="true" />,
    sostenida: <Minus size={16} className="text-muted-foreground" aria-hidden="true" />,
  };
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-foreground">
      {iconos[valor] ?? null}
      {valor}
    </span>
  );
}

export function TablaMerito({ fichas }: { fichas: FichaMerito[] }) {
  if (fichas.length === 0) {
    return (
      <p className="p-6 text-center text-muted-foreground">
        Esta gerencia no tiene personal cargado.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="bg-muted border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground font-bold">
            <th className="px-4 py-3">Persona</th>
            <th className="px-4 py-3">Cumplimiento</th>
            <th className="px-4 py-3">Actividad</th>
            <th className="px-4 py-3">Volumen operativo</th>
            <th className="px-4 py-3">Feedback</th>
            <th className="px-4 py-3">Trayectoria</th>
            <th className="px-4 py-3">Evidencia</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {fichas.map((f) => (
            <tr key={f.employeeId} className="hover:bg-muted/50">
              <td className="px-4 py-3">
                <p className="font-semibold text-foreground">{f.nombre}</p>
                <p className="text-xs text-muted-foreground">{f.position ?? "Sin cargo"}</p>
              </td>
              <td className="px-4 py-3"><Celda dim={f.cumplimiento} /></td>
              <td className="px-4 py-3"><Celda dim={f.actividad} /></td>
              <td className="px-4 py-3"><Celda dim={f.operativo} /></td>
              <td className="px-4 py-3"><Celda dim={f.feedback} /></td>
              <td className="px-4 py-3"><Trayectoria valor={f.trayectoria} /></td>
              <td className="px-4 py-3">
                <span
                  className={`inline-flex items-center gap-1 text-sm ${
                    f.cobertura < f.dimensionesTotales ? "text-warning" : "text-muted-foreground"
                  }`}
                  title="Cuántas dimensiones tienen datos para esta persona. Menos evidencia no significa peor desempeño: significa que hay menos con qué respaldar una decisión."
                >
                  {f.cobertura < f.dimensionesTotales && (
                    <AlertTriangle size={14} aria-hidden="true" />
                  )}
                  {f.cobertura} de {f.dimensionesTotales}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: Escribir la pantalla**

Crear `RRHH/src/app/screens/Merito/Screen.tsx`:

```tsx
"use client";

// Pantalla de apoyo a la decision de ascenso, acotada a una gerencia.
//
// El universo es la gerencia y no toda la nomina a proposito: comparar un
// administrativo con alguien de ventanilla no dice nada, y era el defecto del
// ranking global.

import React from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import { TablaMerito } from "@/app/Componentes/Merito/TablaMerito";
import { getBackendUrl } from "@/app/util/backendUrl";
import type { FichaMerito } from "@/app/Interfas/Interfaces";

const BACKEND_URL = getBackendUrl();

export default function MeritoPage({ departmentId }: { departmentId: number }) {
  const [fichas, setFichas] = React.useState<FichaMerito[]>([]);
  const [cargando, setCargando] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const traer = React.useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const token = localStorage.getItem("token");
      const res = await fetch(`${BACKEND_URL}/stats/merito/${departmentId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`Ficha de mérito: ${res.status}`);
      const json = await res.json();
      setFichas(json.data?.fichas ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setCargando(false);
    }
  }, [departmentId]);

  React.useEffect(() => {
    traer();
  }, [traer]);

  if (cargando) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[40vh] gap-4">
        <div className="w-10 h-10 rounded-full border-4 border-primary border-t-transparent animate-spin" />
        <p className="text-muted-foreground">Cargando fichas…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[40vh] gap-4 text-center px-4">
        <AlertCircle className="w-12 h-12 text-error" />
        <p className="text-muted-foreground max-w-md">{error}</p>
        <button
          onClick={traer}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg"
        >
          <RefreshCw className="w-4 h-4" /> Reintentar
        </button>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-4 sm:p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="font-heading text-2xl font-bold text-foreground">
          Evidencia para decidir un ascenso
        </h1>
        <p className="text-muted-foreground mt-1 max-w-3xl">
          Cada dimensión se muestra por separado, con la cantidad de evidencia que
          la respalda. El sistema no ordena a las personas ni recomienda a nadie:
          reúne lo que sabe para que la decisión la tome quien puede ponderar lo
          que ningún registro captura.
        </p>
      </header>
      <TablaMerito fichas={fichas} />
    </div>
  );
}
```

- [ ] **Step 4: Verificar TypeScript**

```bash
cd /c/Users/Emiliano/Documents/RRHH && npx tsc --noEmit 2>&1 | grep -c "error TS"
```

Esperado: `27`, la línea base. Ni uno más.

- [ ] **Step 5: Verificar contraste**

```bash
cd /c/Users/Emiliano/Documents/RRHH && node scripts/check-contrast.mjs
```

Esperado: `Todos los pares cumplen AA.`

- [ ] **Step 6: Verificar el build**

```bash
cd /c/Users/Emiliano/Documents/RRHH && npm run build
```

Esperado: `Compiled successfully`.

- [ ] **Step 7: Commit**

```bash
cd /c/Users/Emiliano/Documents/RRHH
git add src/app/Interfas/Interfaces.ts src/app/Componentes/Merito/TablaMerito.tsx src/app/screens/Merito/Screen.tsx
git commit -m "feat(merito): ficha comparativa por gerencia para decidir ascensos"
```

---

## Verificación final

- [ ] `Backend_RRHH`: `venv/Scripts/python.exe -m pytest tests/ -q` — 404 tests en verde (366 previos + 38 nuevos).
- [ ] `Backend_RRHH`: `venv/Scripts/python.exe -c "import app.main"` sin error.
- [ ] `Turnero`: `npx vitest run` en verde y `npx tsc --noEmit` sin errores nuevos.
- [ ] `RRHH`: `npx tsc --noEmit` en 27, `node scripts/check-contrast.mjs` en verde, `npm run build` exitoso.
- [ ] Los tres `.env` con `TURNERO_SERVICE_TOKEN` compartido, y ninguno commiteado:

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && git status --short | grep -c "\.env$"
```

Esperado: `0`.

- [ ] Verificar que la corrida nueva quedó registrada con su fórmula:

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -c "
from app.database.database import SessionLocal, SessionLocalObraSocial
from app.routes.stats import sync_productivity_scores
from sqlalchemy import text
db, sdb = SessionLocal(), SessionLocalObraSocial()
sync_productivity_scores(db, sdb)
for r in db.execute(text('SELECT formula, COUNT(*) n FROM ScoreHistorico GROUP BY formula')).all():
    print(r)
db.close(); sdb.close()
"
```

Esperado: dos filas — `eventos_por_sesion_v0` con las corridas viejas y `eventos_por_hora_v1` con la nueva.

## Nota operativa

Con los datos de hoy la ficha va a mostrar **"Sin datos" en la columna de feedback para todos**, porque hay un solo evaluador y el piso es de tres. También va a mostrar "Sin datos" en volumen operativo hasta que Turnero acumule atenciones en producción. Es el comportamiento correcto y esperado.

Eso deja la ficha apoyada en cumplimiento y actividad, que son cumplimiento y volumen digital — **ninguna de las dos mide mérito**. La dimensión que sí lo mide es el feedback de pares, y llenarla no es programar: es correr un ciclo con al menos tres evaluadores por persona. El motor ya está construido y esperando.
