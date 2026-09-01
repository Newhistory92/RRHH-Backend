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
