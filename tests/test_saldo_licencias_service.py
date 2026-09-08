"""
Decisiones puras del saldo de licencias, sin I/O.

Estas tres funciones concentran las reglas que antes vivian sueltas dentro
del endpoint de saldos, donde no se podian probar sin base.
"""

from app.services.saldo_licencias import (
    anios_de_carga,
    saldos_sin_configuracion,
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


def test_saldos_sin_configuracion_devuelve_los_no_cubiertos():
    """El armado de saldos recorre ConfiguracionLicencias, y solo existe 2026:
    un saldo cargado para 2024 no apareceria nunca sin esto."""
    iniciales = {
        (2024, "Vacaciones"): 5,
        (2025, "Vacaciones"): 10,
        (2026, "Vacaciones"): 20,
    }
    cubiertas = {(2026, "Vacaciones")}
    assert saldos_sin_configuracion(iniciales, cubiertas) == [
        (2024, "Vacaciones"),
        (2025, "Vacaciones"),
    ]


def test_saldos_sin_configuracion_ordena_por_anio():
    """La pantalla los muestra en orden; que el orden lo fije esta funcion
    evita que dependa del orden de iteracion de un dict."""
    iniciales = {(2026, "Vacaciones"): 1, (2024, "Vacaciones"): 2}
    assert saldos_sin_configuracion(iniciales, set()) == [
        (2024, "Vacaciones"),
        (2026, "Vacaciones"),
    ]


def test_saldos_sin_configuracion_sin_faltantes_devuelve_vacio():
    iniciales = {(2026, "Vacaciones"): 20}
    assert saldos_sin_configuracion(iniciales, {(2026, "Vacaciones")}) == []


def test_anios_de_carga_son_el_actual_y_los_dos_previos():
    assert anios_de_carga(2026) == [2026, 2025, 2024]


def test_anios_de_carga_van_de_mas_nuevo_a_mas_viejo():
    """La pantalla los lista en ese orden y el mas relevante es el actual."""
    assert anios_de_carga(2030)[0] == 2030
