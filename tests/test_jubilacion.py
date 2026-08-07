from datetime import date

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
