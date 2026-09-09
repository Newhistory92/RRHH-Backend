"""
Decisiones puras del saldo de licencias, sin I/O.

Estas tres funciones concentran las reglas que antes vivian sueltas dentro
del endpoint de saldos, donde no se podian probar sin base.
"""

from app.services.saldo_licencias import (
    anios_de_carga,
    total_del_anio,
)


def test_saldo_inicial_manda_sobre_vacaciones():
    """Lo cargado a mano reemplaza al calculo por antiguedad. Si no lo hiciera,
    la carga inicial no tendria ningun efecto sobre vacaciones."""
    assert total_del_anio(5, es_vacaciones=True, dias_vac=20, dias_totales=30) == 5


def test_saldo_inicial_manda_sobre_las_demas():
    assert total_del_anio(3, es_vacaciones=False, dias_vac=20, dias_totales=30) == 3


def test_saldo_inicial_en_cero_manda_igual():
    """Cero cargado es 'no le queda nada'. Confundirlo con 'sin cargar' le
    otorgaria los dias completos, que es exactamente el bug que motivo todo."""
    assert total_del_anio(0, es_vacaciones=True, dias_vac=20, dias_totales=30) == 0


def test_sin_saldo_inicial_vacaciones_usa_la_antiguedad():
    assert total_del_anio(None, es_vacaciones=True, dias_vac=20, dias_totales=30) == 20


def test_sin_saldo_inicial_el_resto_usa_la_configuracion():
    assert total_del_anio(None, es_vacaciones=False, dias_vac=20, dias_totales=30) == 30


def test_anios_de_carga_son_el_actual_y_los_dos_previos():
    assert anios_de_carga(2026) == [2026, 2025, 2024]


def test_anios_de_carga_van_de_mas_nuevo_a_mas_viejo():
    """La pantalla los lista en ese orden y el mas relevante es el actual."""
    assert anios_de_carga(2030)[0] == 2030
