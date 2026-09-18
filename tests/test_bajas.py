"""
Reglas puras de la baja, sin base ni TestClient.

baja_vigente es la definicion unica de "esta de baja": la usan el recorte de
permisos, el job diario y los dos cortes de computo (vacaciones y asistencia):
una sola regla para todos los caminos.
"""

from datetime import date, datetime

from app.services.bajas import (
    MOTIVOS_DE_BAJA, a_date, antiguedad_en_anios, baja_vigente,
)

HOY = date(2026, 9, 17)


def _baja(fecha_baja, fecha_reingreso=None, motivo="Renuncia"):
    return {"motivo": motivo, "fechaBaja": fecha_baja,
            "fechaReingreso": fecha_reingreso}


def test_el_catalogo_tiene_los_siete_motivos_acordados():
    assert MOTIVOS_DE_BAJA == (
        "Jubilación", "Renuncia", "Despido", "Fin de contrato",
        "Fallecimiento", "Traslado a otro organismo", "Abandono de cargo",
    )


def test_sin_bajas_no_esta_de_baja():
    assert baja_vigente([], HOY) is None


def test_una_baja_cumplida_esta_vigente():
    b = _baja(date(2026, 9, 1))
    assert baja_vigente([b], HOY) is b


def test_la_baja_de_hoy_ya_esta_vigente():
    b = _baja(HOY)
    assert baja_vigente([b], HOY) is b


def test_una_baja_futura_todavia_no_tiene_efecto():
    """Se carga cuando se sabe; la persona sigue trabajando hasta ese dia."""
    assert baja_vigente([_baja(date(2026, 12, 1))], HOY) is None


def test_una_baja_con_reingreso_ya_no_tiene_efecto():
    """La persona volvio: la fila queda en el historial pero no recorta nada."""
    b = _baja(date(2025, 3, 1), fecha_reingreso=date(2026, 1, 10))
    assert baja_vigente([b], HOY) is None


def test_entre_una_cerrada_y_una_abierta_gana_la_abierta():
    cerrada = _baja(date(2024, 2, 1), fecha_reingreso=date(2024, 8, 1))
    abierta = _baja(date(2026, 5, 1))
    assert baja_vigente([cerrada, abierta], HOY) is abierta


def test_con_varias_abiertas_gana_la_mas_reciente():
    """El endpoint no permite dos abiertas, pero la regla no depende de eso."""
    vieja = _baja(date(2020, 1, 1))
    nueva = _baja(date(2026, 1, 1))
    assert baja_vigente([vieja, nueva], HOY) is nueva


def test_acepta_datetime_de_pyodbc():
    """pyodbc devuelve datetime donde el esquema dice DATE."""
    b = _baja(datetime(2026, 9, 1, 0, 0))
    assert baja_vigente([b], HOY) is b


def test_a_date_normaliza_datetime_a_date():
    assert a_date(datetime(2026, 9, 1, 13, 45)) == date(2026, 9, 1)


def test_a_date_deja_pasar_un_date():
    assert a_date(date(2026, 9, 1)) == date(2026, 9, 1)


def test_a_date_de_none_es_none():
    assert a_date(None) is None


def test_antiguedad_cuenta_los_anios_entre_ingreso_y_baja():
    assert antiguedad_en_anios(date(2016, 9, 1), date(2026, 9, 1)) == 10.0


def test_antiguedad_con_un_decimal():
    assert antiguedad_en_anios(date(2024, 3, 1), date(2026, 9, 1)) == 2.5


def test_antiguedad_sin_ingreso_es_none():
    """No se inventa un cero, que se leeria como 'entro y se fue el mismo dia'."""
    assert antiguedad_en_anios(None, date(2026, 9, 1)) is None


def test_antiguedad_con_baja_anterior_al_ingreso_es_none():
    assert antiguedad_en_anios(date(2026, 9, 1), date(2020, 1, 1)) is None
