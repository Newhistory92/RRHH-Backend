"""
El ciclo de vacaciones: que anio rige segun la fecha.

La regla es un borde, asi que se prueba el dia de cada lado y no un mes
cualquiera del medio: si el corte se corre un dia, estos tests lo dicen.
"""

from datetime import date

import pytest

from app.services.saldo_licencias import anios_de_ventana, ciclo_vacaciones


@pytest.mark.parametrize("hoy, esperado", [
    (date(2026, 9, 30), 2025),   # vispera del corte
    (date(2026, 10, 1), 2026),   # el corte
    (date(2026, 12, 31), 2026),  # fin de anio, ya habilitado
    (date(2027, 1, 1), 2026),    # anio nuevo, todavia rige el anterior
    (date(2027, 9, 30), 2026),
    (date(2027, 10, 1), 2027),
])
def test_el_ciclo_cambia_el_1_de_octubre(hoy, esperado):
    assert ciclo_vacaciones(hoy) == esperado


def test_la_ventana_va_del_ciclo_hacia_atras():
    """Tres anios contando el ciclo, del mas nuevo al mas viejo."""
    assert anios_de_ventana(2026) == [2026, 2025, 2024]
