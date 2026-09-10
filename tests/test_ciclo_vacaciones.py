"""
El ciclo de vacaciones: que anio rige segun la fecha.

La regla es un borde, asi que se prueba el dia de cada lado y no un mes
cualquiera del medio: si el corte se corre un dia, estos tests lo dicen.
"""

from datetime import date

import pytest

from app.services.saldo_licencias import anios_de_ventana, ciclo_vacaciones, expandir_por_anio


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


CONFIGS = [
    {"categoria": "Vacaciones", "contrato": "permanente", "diasTotales": 0},
    {"categoria": "Particular", "contrato": "permanente", "diasTotales": 5},
]


def test_cada_configuracion_se_repite_en_cada_anio_de_la_ventana():
    """La configuracion ya no trae anio: los anios los pone el codigo."""
    filas = expandir_por_anio(CONFIGS, [2026, 2025], {})
    assert len(filas) == 4
    assert {f["anio"] for f in filas} == {2026, 2025}
    assert {f["tipoLicencia"] for f in filas} == {"Vacaciones", "Particular"}


def test_el_consumo_se_imputa_al_anio_y_categoria_que_corresponde():
    filas = expandir_por_anio(
        CONFIGS, [2026, 2025], {(2025, "particular"): 3},
    )
    fila = next(f for f in filas if f["anio"] == 2025 and f["tipoLicencia"] == "Particular")
    assert fila["diasConsumidos"] == 3
    otra = next(f for f in filas if f["anio"] == 2026 and f["tipoLicencia"] == "Particular")
    assert otra["diasConsumidos"] == 0


def test_el_consumo_se_cruza_sin_importar_mayusculas():
    """ConsumoLicencias.tipo lo escribe quien aprueba y no respeta el casing
    de la categoria configurada."""
    filas = expandir_por_anio(CONFIGS, [2026], {(2026, "vacaciones"): 4})
    fila = next(f for f in filas if f["tipoLicencia"] == "Vacaciones")
    assert fila["diasConsumidos"] == 4


from app.services.saldo_licencias import anios_de_vacaciones_con_datos


def test_sin_historial_previo_solo_se_muestra_el_anio_vigente():
    """El caso comun: un empleado sin saldo cargado ni consumo en anios
    anteriores no tiene por que ver dos filas mas en 0/0."""
    anios = anios_de_vacaciones_con_datos(
        ciclo=2025, categoria="Vacaciones",
        saldos_iniciales={}, consumidos_por_clave={},
    )
    assert anios == [2025]


def test_un_anio_anterior_con_saldo_cargado_se_muestra():
    anios = anios_de_vacaciones_con_datos(
        ciclo=2025, categoria="Vacaciones",
        saldos_iniciales={(2024, "Vacaciones"): 5}, consumidos_por_clave={},
    )
    assert set(anios) == {2025, 2024}


def test_un_anio_anterior_con_consumo_se_muestra_aunque_no_tenga_saldo_cargado():
    anios = anios_de_vacaciones_con_datos(
        ciclo=2025, categoria="Vacaciones",
        saldos_iniciales={}, consumidos_por_clave={(2023, "vacaciones"): 3},
    )
    assert set(anios) == {2025, 2023}


def test_el_anio_vigente_se_muestra_aunque_este_vacio():
    """Es el "anio correspondiente" de la regla: siempre aparece, tenga o no
    datos cargados."""
    anios = anios_de_vacaciones_con_datos(
        ciclo=2025, categoria="Vacaciones",
        saldos_iniciales={}, consumidos_por_clave={},
    )
    assert 2025 in anios
