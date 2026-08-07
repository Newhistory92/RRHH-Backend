from datetime import date, datetime

from app.services.asistencia_recalc import rango_de_calculo
from app.services.jubilacion import jubilacion_cumplida

HOY = date(2026, 8, 7)


def test_sin_fecha_no_esta_jubilado():
    assert jubilacion_cumplida(None, HOY) is False


def test_una_fecha_futura_todavia_no_jubila():
    # RRHH puede cargar la fecha con anticipacion: la persona sigue trabajando.
    assert jubilacion_cumplida(date(2026, 12, 1), HOY) is False


def test_manana_todavia_no_jubila():
    assert jubilacion_cumplida(date(2026, 8, 8), HOY) is False


def test_la_fecha_de_hoy_ya_jubila():
    assert jubilacion_cumplida(HOY, HOY) is True


def test_una_fecha_pasada_jubila():
    assert jubilacion_cumplida(date(2026, 1, 15), HOY) is True


# -- Rango de calculo con la jubilacion como cota superior ---------------------

INICIO_MODULO = date(2026, 1, 1)


def test_sin_jubilacion_el_rango_llega_hasta_hoy():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1), None, HOY)
    assert r == (date(2026, 1, 1), HOY)


def test_la_jubilacion_corta_el_rango():
    # Jubilado el 30/06: no se calculan dias posteriores.
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1),
                         date(2026, 6, 30), HOY)
    assert r == (date(2026, 1, 1), date(2026, 6, 30))


def test_una_jubilacion_futura_no_recorta_nada():
    # La fecha esta cargada pero todavia no llego: se calcula hasta hoy igual.
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1),
                         date(2026, 12, 1), HOY)
    assert r == (date(2026, 1, 1), HOY)


def test_una_jubilacion_anterior_al_inicio_del_modulo_no_da_rango():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1),
                         date(2025, 5, 1), HOY)
    assert r is None


def test_el_ingreso_sigue_siendo_la_cota_inferior():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2026, 4, 10), None, HOY)
    assert r == (date(2026, 4, 10), HOY)


def test_ingreso_y_jubilacion_en_el_mismo_anio():
    # hoy despues de jubilacion para que sea ella la cota, no hoy.
    r = rango_de_calculo(2026, INICIO_MODULO, date(2026, 3, 1),
                         date(2026, 9, 15), date(2026, 12, 31))
    assert r == (date(2026, 3, 1), date(2026, 9, 15))


def test_jubilarse_el_mismo_dia_del_ingreso_da_un_solo_dia():
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
