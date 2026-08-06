from datetime import date

import pytest

from app.services.asistencia_justificaciones import (
    VENTANA_JUSTIFICACION_DIAS, validar_fecha_justificable,
)

HOY = date(2026, 8, 6)


def test_la_ventana_es_de_treinta_dias():
    assert VENTANA_JUSTIFICACION_DIAS == 30


def test_hoy_se_puede_justificar():
    validar_fecha_justificable(HOY, HOY)


def test_ayer_se_puede_justificar():
    validar_fecha_justificable(date(2026, 8, 5), HOY)


def test_el_borde_exacto_de_treinta_dias_se_puede_justificar():
    # 2026-07-07 esta exactamente 30 dias antes de 2026-08-06.
    validar_fecha_justificable(date(2026, 7, 7), HOY)


def test_treinta_y_un_dias_atras_ya_no_se_puede():
    with pytest.raises(ValueError, match="30 dias"):
        validar_fecha_justificable(date(2026, 7, 6), HOY)


def test_una_fecha_futura_no_se_puede_justificar():
    with pytest.raises(ValueError, match="futura"):
        validar_fecha_justificable(date(2026, 8, 7), HOY)
