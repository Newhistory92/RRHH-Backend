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
