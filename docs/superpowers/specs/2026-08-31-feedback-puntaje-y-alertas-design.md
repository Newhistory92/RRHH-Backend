# Puntaje de Feedback 360 y alertas de conducta — Diseño

**Objetivo:** Que las 68 respuestas de `RespuestaFeedback` que hoy se recolectan y no se usan produzcan (a) un puntaje de feedback por empleado que se sostenga estadísticamente, y (b) alertas de conducta separadas del puntaje. Corrige de paso un bug activo que invierte el significado de 12 preguntas.

**Alcance:** No se toca `Employee.productivityScore` ni `sync_productivity_scores`. El puntaje de feedback es una dimensión propia, en paralelo. La composición de ambos en un score único queda para una iteración posterior.

---

## Problema que resuelve

El banco de preguntas mezcla dos polaridades sin distinguirlas:

- *"¿La persona trata a sus compañeros con respeto?"* → 5 = "Siempre" = **bueno**
- *"¿Genera conflictos innecesarios?"* → 5 = "Siempre" = **malo**

`Pregunta` no tiene columna de polaridad, y `get_received_feedback` hace `AVG(valorEscala)` plano. Consecuencia verificada en datos reales: el empleado 9 respondió 5 en *"genera conflictos"*, 5 en *"genera retrabajos"* y 5 en *"genera un ambiente tenso"*, y esos valores **suben** su promedio de categoría. La pestaña de Feedback 360° presenta hoy como fortaleza lo que es la peor respuesta posible.

Además, `get_received_feedback` no llama a `_check_self_or_admin` (a diferencia del resto del router) y exige solo `feedback.participar`, permiso que todos los roles tienen vía `_BASE`. Hoy cualquier empleado puede leer las fortalezas y debilidades de cualquier otro pasando su ID.

---

## Decisiones tomadas con el usuario (no volver a preguntar)

| Decisión | Valor |
|---|---|
| Alcance de esta iteración | Corregir polaridad y exponer el feedback como dimensión propia. `productivityScore` no se toca. |
| Mínimo de evaluadores para mostrar puntaje | **3 evaluadores distintos.** Por debajo, `null` — nunca un número. |
| Categorías de riesgo en el puntaje | **Fuera del promedio.** Generan alertas propias. No se diluyen ni se compensan con desempeño. |
| Alertas y el mínimo de 3 | **Mismo piso de participación (B1).** Alcanzados 3 evaluadores, una alerta se muestra aunque la reporte una sola persona, indicando "1 de N". |
| Escala de salida | **1–5**, la misma en que se responde. Un 4.2 se lee contra "Casi siempre". |
| Período | **Período actual** (`get_periodo_actual`). |
| Dónde se marca la polaridad | Columna en `Pregunta`, sembrada desde código. No hay endpoint de alta de preguntas. |
| Visibilidad | **Solo RRHH.** El empleado no ve su propio puntaje. |

---

## Arquitectura

Tres funciones puras y dos endpoints. La lógica delicada no toca la base, siguiendo el patrón de `app/services/asistencia_calc.py`.

```
Pregunta.esInversa (columna nueva)
   │
   └─→ normalizar_valor()        pura — corrige polaridad, deja 5=mejor 1=peor
          │
          ├─→ puntaje_feedback()  pura — promedio de desempeño + piso de evaluadores
          └─→ detectar_alertas()  pura — banderas de conducta con su respaldo
                 │
                 ├─→ GET /feedback/puntajes        (nuevo, bulk, rrhh.gestionar)
                 └─→ GET /feedback/received/{id}   (corregido)
                        │
                        └─→ Columna "Feedback" en el ranking de Estadísticas
```

---

## Componente 1 · Polaridad

**Archivo:** `app/database/feedback_preguntas.py`

Columna nueva, DDL idempotente siguiendo `ensure_columnas_exencion`:

```sql
IF COL_LENGTH('Pregunta','esInversa') IS NULL
ALTER TABLE Pregunta ADD esInversa BIT NOT NULL DEFAULT 0;
```

El nombre sigue la convención del propio módulo (`esAmbienteGeneral`, `soloLiderazgo`).

`PREGUNTAS_BASE` y `PREGUNTAS_AMBIENTE_GENERAL` suman un campo `esInversa` a su tupla. Las 12 preguntas invertidas:

**De par (9):**
1. ¿Has presenciado conductas inapropiadas por parte de esta persona? — *Respeto y convivencia*
2. ¿Genera conflictos innecesarios? — *Respeto y convivencia*
3. ¿Su trabajo genera retrabajos para otros? — *Responsabilidad*
4. ¿Alguna persona del equipo genera un ambiente tenso? — *Riesgos laborales*
5. ¿Evitás interactuar con esta persona cuando es posible? — *Riesgos laborales*
6. ¿Considerás que esta persona afecta negativamente al equipo? — *Riesgos laborales*
7. ¿Has observado faltas de respeto hacia compañeros? — *Conductas de riesgo*
8. ¿Has observado conductas intimidantes o agresivas? — *Conductas de riesgo*
9. ¿Creés que esta persona discrimina o hace comentarios ofensivos? — *Conductas de riesgo*

**De ambiente general (3):**
10. ¿Existe favoritismo?
11. ¿Te sentís sobrecargado de trabajo?
12. ¿Has pensado en renunciar por el ambiente laboral?

**No invertida, aunque esté en una categoría de riesgo:** *¿Te sentís cómodo trabajando con esta persona?* — un 5 ahí es bueno.

**Migración de datos ya sembrados.** `ensure_table` solo siembra si `Pregunta` está vacía, y en esta base ya hay 38 filas. Hace falta un `UPDATE` idempotente que marque `esInversa = 1` por texto exacto para las 12, ejecutado en el mismo `ensure_table`. Sin esto la columna queda en 0 para todas y el bug persiste.

**Interfaz:**

```python
def normalizar_valor(valor: int, es_inversa: bool) -> int:
    """6 - valor si es inversa. Deja siempre 5=mejor, 1=peor."""
```

`get_preguntas` agrega `esInversa` al dict que devuelve.

---

## Componente 2 · Puntaje de feedback

**Archivo nuevo:** `app/services/feedback_score.py`

**Qué entra:** preguntas de escala, con evaluado (`evaluadoEmployeeId IS NOT NULL`), de categorías de **desempeño**:

```python
CATEGORIAS_DESEMPENO = frozenset({
    "Respeto y convivencia", "Comunicación", "Responsabilidad",
    "Profesionalismo", "Liderazgo", "Confianza",
})
CATEGORIAS_RIESGO = frozenset({"Riesgos laborales", "Conductas de riesgo"})
```

Quedan fuera de ambos conjuntos, a propósito: *Ambiente laboral general* (no es sobre una persona) y *Preguntas abiertas* (texto libre, no numérico).

**Interfaz:**

```python
MIN_EVALUADORES = 3

@dataclass(frozen=True)
class RespuestaNorm:
    evaluadorId: int
    categoria: str
    valor: int          # ya normalizado, 5=mejor
    esRiesgo: bool
    preguntaTexto: str

@dataclass(frozen=True)
class PuntajeFeedback:
    promedio: float | None        # None si no llega al mínimo
    evaluadores: int
    suficiente: bool
    porCategoria: dict[str, float]   # vacío si no es suficiente

def puntaje_feedback(respuestas: list[RespuestaNorm]) -> PuntajeFeedback:
    """
    Promedio de las respuestas de desempeño, en escala 1-5.

    Devuelve promedio=None cuando hay menos de MIN_EVALUADORES evaluadores
    distintos: con menos, el numero seria la opinion de una o dos personas
    presentada como medicion, y ademas haria deducible quien evaluo.
    """
```

El conteo de evaluadores usa **evaluadores distintos que respondieron algo sobre esa persona**, no respuestas. Una persona que contesta 30 preguntas sigue siendo un evaluador.

Cuenta cualquier respuesta sobre esa persona, sea de desempeño o de riesgo: el piso mide **participación del grupo** —cuánta gente la evaluó, que es lo que protege el anonimato— y no cuántas respuestas alimentan el promedio. El mismo conteo se usa para el puntaje y para las alertas, así ambos se habilitan juntos.

---

## Componente 3 · Alertas de conducta

Mismo archivo. Opera sobre las categorías de **riesgo**, por pregunta individual — no por promedio de categoría, porque esas categorías tienen polaridad mixta.

```python
UMBRAL_ALERTA = 2   # sobre valor normalizado: las dos peores respuestas

@dataclass(frozen=True)
class AlertaConducta:
    preguntaTexto: str
    categoria: str
    reportan: int        # evaluadores con valor normalizado <= UMBRAL_ALERTA
    evaluadores: int     # total de evaluadores de esa persona

def detectar_alertas(respuestas: list[RespuestaNorm]) -> list[AlertaConducta]:
    """
    Banderas de conducta para RRHH.

    Se aplican el mismo piso de participacion que el puntaje: con menos de
    MIN_EVALUADORES no se devuelve nada, porque en un grupo chico mostrar la
    alerta hace deducible quien la reporto. Alcanzado el piso, un solo reporte
    ya genera alerta: no se exige corroboracion, se informa el respaldo
    ("1 de 5") para que RRHH calibre.
    """
```

**Sobre el umbral:** con la escala estándar `["Siempre", "Casi siempre", "Algunas veces", "Rara vez", "Nunca"]` mapeada a 5..1, una pregunta inversa respondida "Casi siempre" (4 crudo) normaliza a 2 y dispara alerta. "Algunas veces" (3) normaliza a 3 y no dispara. Es deliberado: el umbral marca las dos peores respuestas posibles, no la ambigüedad del medio.

---

## Componente 4 · Endpoints

**`GET /feedback/puntajes`** — nuevo. Bulk para el ranking.

- Permiso: **`rrhh.gestionar`**, no `feedback.participar`.
- Devuelve, por empleado con respuestas en el período: `{ employeeId, promedio, evaluadores, suficiente, alertas: n }`.
- No incluye el texto de las alertas: el ranking solo muestra que existen. El detalle se pide por empleado.

**`GET /feedback/received/{employee_id}`** — corregido.

1. Aplica normalización de polaridad (hoy no lo hace: **es el bug**).
2. Separa desempeño de riesgo.
3. Agrega `_check_self_or_admin`, que hoy le falta.
4. Sube el permiso a `rrhh.gestionar` para lectura de terceros.

Las fortalezas y debilidades por categoría se siguen devolviendo, ahora sobre valores normalizados y solo de categorías de desempeño.

---

## Componente 5 · Frontend

**Archivo:** `src/app/Componentes/ComponEstadistica/Productivity.tsx`

Columna nueva "Feedback". Solo dos estados posibles, porque puntaje y alertas
comparten el mismo piso de 3 evaluadores: o se muestran ambos, o ninguno. **No
existe el caso "Datos insuficientes con ícono de alerta"** — el implementador no
debe construir ese estado.

- **Suficiente:** el número (ej. `4.2`) y debajo, chico, `5 evaluadores`. Si además tiene alertas, ícono de advertencia junto al número con `title` indicando cuántas. El color no puede ser el único indicador — va ícono, siguiendo la regla del proyecto.
- **Insuficiente:** `Datos insuficientes` en `text-muted-foreground`, con `title` explicando que hacen falta 3 evaluadores. Sin ícono de alerta, aunque internamente existan respuestas de riesgo.

El modal `ComoSeCalculaModal` suma una línea explicando qué es esta columna y por qué a veces dice "Datos insuficientes".

---

## Testing

Las tres funciones puras se testean sin base, con `pytest`:

**Normalización**
- Pregunta directa: el valor no cambia.
- Pregunta inversa: 5→1, 4→2, 1→5.
- El punto medio 3 no cambia en ninguna de las dos.

**Puntaje**
- Con 2 evaluadores devuelve `promedio=None` y `suficiente=False`.
- Con 3 evaluadores devuelve promedio.
- Un evaluador que responde 30 preguntas cuenta como **1** evaluador, no 30.
- Las respuestas de categorías de riesgo **no** entran al promedio.
- Las de ambiente general y texto libre no entran.
- Una pregunta inversa mal respondida **baja** el promedio (regresión del bug).

**Alertas**
- Con menos de 3 evaluadores no devuelve alertas.
- Con 3+ evaluadores y un solo reporte: devuelve la alerta con `reportan=1`.
- Valor normalizado 3 no dispara; 2 y 1 sí.
- Las categorías de desempeño nunca generan alertas.

**Endpoints** con `FakeSession`: que `/puntajes` exija `rrhh.gestionar`, y que `/received/{id}` rechace a un empleado pidiendo el ID de otro.

---

## Fuera de alcance

- Componer feedback y `productivityScore` en un score único.
- Normalización por área o percentiles.
- Que el empleado vea su propio puntaje — decidido que no.
- UI de administración del banco de preguntas.
- Ponderar categorías entre sí dentro del puntaje: todas pesan igual en esta iteración.

## Riesgo conocido

Con los datos actuales — un solo evaluador — **ni el puntaje ni las alertas se mostrarán para nadie**. Es el comportamiento correcto y esperado, pero significa que la funcionalidad no se puede validar visualmente contra datos reales hasta que al menos 3 personas completen un ciclo. La verificación de esta iteración es por tests, no por pantalla.
