"""
Tests del reparto de score para areas exentas.

La funcion es pura: recibe scores, exentos y horas; devuelve scores finales.
Sin base de datos, sin I/O.
"""

from app.routes.stats import aplicar_score_exentos


def test_el_exento_sin_horas_recibe_el_promedio_limpio():
    scores = {1: 6.0, 2: 4.0, 3: 0.0}
    resultado = aplicar_score_exentos(scores, exentos={3}, horas={})
    assert resultado[3] == 5.0  # promedio de 6.0 y 4.0
    assert resultado[1] == 6.0  # los no exentos no se tocan
    assert resultado[2] == 4.0


def test_los_exentos_se_desempatan_por_horas_conservando_el_promedio():
    scores = {1: 6.0, 2: 4.0, 3: 0.0, 4: 0.0}
    # 3 tiene mejor saldo que 4
    resultado = aplicar_score_exentos(scores, exentos={3, 4}, horas={3: 10.0, 4: -10.0})
    assert resultado[3] > resultado[4], "el de mejor asistencia debe quedar arriba"
    promedio_grupo = (resultado[3] + resultado[4]) / 2
    assert abs(promedio_grupo - 5.0) < 0.01, "el promedio del grupo se conserva"


def test_exentos_con_el_mismo_saldo_reciben_todos_el_promedio():
    scores = {1: 6.0, 2: 4.0, 3: 0.0, 4: 0.0}
    resultado = aplicar_score_exentos(scores, exentos={3, 4}, horas={3: 5.0, 4: 5.0})
    assert resultado[3] == resultado[4] == 5.0


def test_el_exento_sin_horas_no_se_mezcla_con_los_que_si_tienen():
    scores = {1: 6.0, 2: 4.0, 3: 0.0, 4: 0.0}
    resultado = aplicar_score_exentos(scores, exentos={3, 4}, horas={3: 10.0})
    assert resultado[4] == 5.0, "sin dato de asistencia recibe el promedio limpio"


def test_sin_no_exentos_no_se_pisa_el_score_previo():
    scores = {1: 3.0, 2: 2.0}
    resultado = aplicar_score_exentos(scores, exentos={1, 2}, horas={})
    assert resultado == scores, "sin base para promediar, no se toca nada"


def test_promedio_cero_no_empeora_a_nadie():
    scores = {1: 0.0, 2: 0.0, 3: 0.0}
    resultado = aplicar_score_exentos(scores, exentos={3}, horas={3: 10.0})
    assert resultado[3] == 0.0


def test_el_ajuste_no_supera_el_quince_por_ciento_del_promedio():
    scores = {1: 10.0, 2: 10.0, 3: 0.0, 4: 0.0}
    resultado = aplicar_score_exentos(scores, exentos={3, 4}, horas={3: 999.0, 4: -999.0})
    assert resultado[3] <= 10.0 * 1.15
    assert resultado[4] >= 10.0 * 0.85


# ── "Sin datos" no es cero ────────────────────────────────────────────────────
#
# Un empleado que no matchea contra los logs de ObraSocial nunca fue medido.
# Escribirle 0.0 lo vuelve indistinguible de alguien medido en cero, y en el
# ranking se lee como bajo desempeno. Ahora llega como None y tiene que
# atravesar el reparto sin romperlo ni contaminar el promedio.


def test_el_no_medido_no_entra_al_promedio_de_los_exentos():
    """
    Si el None contara como 0 bajaria el promedio que se le reparte a los
    exentos, castigandolos por un dato que nadie tiene.
    """
    scores = {1: 6.0, 2: 4.0, 3: None, 9: None}
    resultado = aplicar_score_exentos(scores, exentos={3}, horas={})
    assert resultado[3] == 5.0  # promedio de 6.0 y 4.0, sin el None


def test_el_no_medido_que_no_es_exento_sigue_sin_dato():
    scores = {1: 6.0, 2: 4.0, 9: None}
    resultado = aplicar_score_exentos(scores, exentos={3}, horas={})
    assert resultado[9] is None


def test_sin_ningun_medido_no_se_inventa_un_promedio():
    scores = {1: None, 2: None, 3: None}
    resultado = aplicar_score_exentos(scores, exentos={3}, horas={})
    assert resultado == {1: None, 2: None, 3: None}


def test_el_exento_no_medido_igual_recibe_el_promedio():
    """
    La exencion existe para eso: el area no genera logs, asi que su None es
    esperado y se reemplaza por el promedio de los demas.
    """
    scores = {1: 8.0, 2: 6.0, 3: None}
    resultado = aplicar_score_exentos(scores, exentos={3}, horas={})
    assert resultado[3] == 7.0
