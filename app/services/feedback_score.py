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
