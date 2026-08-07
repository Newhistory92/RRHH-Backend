from datetime import date

from app.routes.licenses import calcular_dias_vacaciones

INGRESO = date(2010, 1, 1)


def test_sin_fecha_de_corte_usa_hoy():
    # Se compara contra hoy explicito en vez de contra un numero fijo: la
    # antiguedad crece con el calendario y un valor hardcodeado haria que el
    # test empezara a fallar solo, sin que nadie toque el codigo.
    assert (calcular_dias_vacaciones("permanente", INGRESO)
            == calcular_dias_vacaciones("permanente", INGRESO, date.today()))


def test_la_fecha_de_corte_congela_la_antiguedad():
    # Jubilado en 2018: 8 anios de antiguedad, no los que corresponderian hoy.
    assert calcular_dias_vacaciones(
        "permanente", INGRESO, date(2018, 1, 1)) == 15


def test_la_antiguedad_no_sigue_creciendo_despues_del_corte():
    # El mismo corte da el mismo resultado sin importar cuando se pregunte.
    primero = calcular_dias_vacaciones("permanente", INGRESO, date(2018, 1, 1))
    segundo = calcular_dias_vacaciones("permanente", INGRESO, date(2018, 1, 1))
    assert primero == segundo == 15


def test_un_corte_en_el_primer_anio_da_proporcional():
    assert calcular_dias_vacaciones(
        "permanente", INGRESO, date(2010, 10, 1)) == 7


def test_un_corte_antes_de_los_seis_meses_no_da_derecho():
    assert calcular_dias_vacaciones(
        "permanente", INGRESO, date(2010, 4, 1)) == 0


def test_contratado_con_corte_sigue_topeado_en_diez():
    assert calcular_dias_vacaciones(
        "contratado", INGRESO, date(2018, 1, 1)) == 10
