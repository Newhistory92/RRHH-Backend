"""
El rango de dias que se le calcula a un empleado en un anio.

Acotado por abajo por el inicio del modulo y el ingreso, y por arriba por el
fin del anio, hoy y la fecha de baja. Es lo que congela el saldo de quien se
fue, sin ningun caso especial.
"""

from datetime import date, datetime

from app.services.asistencia_recalc import rango_de_calculo

HOY = date(2026, 8, 7)


# -- Rango de calculo con la baja como cota superior ---------------------------

INICIO_MODULO = date(2026, 1, 1)


def test_sin_baja_el_rango_llega_hasta_hoy():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1), None, HOY)
    assert r == (date(2026, 1, 1), HOY)


def test_la_baja_corta_el_rango():
    # Dado de baja el 30/06: no se calculan dias posteriores.
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1),
                         date(2026, 6, 30), HOY)
    assert r == (date(2026, 1, 1), date(2026, 6, 30))


def test_una_baja_futura_no_recorta_nada():
    # La fecha esta cargada pero todavia no llego: se calcula hasta hoy igual.
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1),
                         date(2026, 12, 1), HOY)
    assert r == (date(2026, 1, 1), HOY)


def test_una_baja_anterior_al_inicio_del_modulo_no_da_rango():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1),
                         date(2025, 5, 1), HOY)
    assert r is None


def test_el_ingreso_sigue_siendo_la_cota_inferior():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2026, 4, 10), None, HOY)
    assert r == (date(2026, 4, 10), HOY)


def test_ingreso_y_baja_en_el_mismo_anio():
    # hoy despues de la baja para que sea ella la cota, no hoy.
    r = rango_de_calculo(2026, INICIO_MODULO, date(2026, 3, 1),
                         date(2026, 9, 15), date(2026, 12, 31))
    assert r == (date(2026, 3, 1), date(2026, 9, 15))


def test_irse_el_mismo_dia_del_ingreso_da_un_solo_dia():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2026, 5, 20),
                         date(2026, 5, 20), HOY)
    assert r == (date(2026, 5, 20), date(2026, 5, 20))


def test_un_anio_pasado_se_calcula_entero_sin_recortar_por_hoy():
    r = rango_de_calculo(2026, date(2025, 1, 1), date(2020, 3, 1), None,
                         date(2027, 4, 1))
    assert r == (date(2026, 1, 1), date(2026, 12, 31))


def test_acepta_datetime_de_pyodbc_y_devuelve_date():
    # pyodbc puede devolver datetime en una columna DATE; datetime hereda de
    # date, asi que un guard mal escrito lo deja pasar sin normalizar.
    r = rango_de_calculo(2026, INICIO_MODULO, datetime(2020, 3, 1, 9, 30),
                         datetime(2026, 6, 30, 17, 0), HOY)
    assert r == (date(2026, 1, 1), date(2026, 6, 30))
    assert type(r[0]) is date and type(r[1]) is date
