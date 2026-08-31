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
