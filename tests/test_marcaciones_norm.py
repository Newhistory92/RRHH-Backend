from datetime import datetime

from app.services import marcaciones_norm as n

JORNADA_7_A_13 = n.HorarioDia(horaInicio=7.0, horaFin=13.0, horasTrabajo=6.0)


def _m(*hms):
    """(hora, minuto) o (hora, minuto, segundo) -> datetime del 2026-07-30."""
    return [datetime(2026, 7, 30, *hm) for hm in hms]


# -- Deduplicacion ------------------------------------------------------------

def test_rebote_de_tres_segundos_colapsa_en_una_marca():
    marcas = _m((8, 9, 21), (8, 9, 23), (8, 9, 24))
    assert n.deduplicar(marcas) == [datetime(2026, 7, 30, 8, 9, 21)]


def test_marcas_separadas_por_seis_minutos_no_colapsan():
    marcas = _m((7, 0), (7, 6))
    assert n.deduplicar(marcas) == marcas


def test_el_limite_exacto_de_la_ventana_no_colapsa():
    marcas = _m((7, 0), (7, 5))
    assert n.deduplicar(marcas) == marcas


def test_rafaga_larga_no_se_encadena_mas_alla_de_la_ventana():
    # Cinco marcas de a dos minutos: 7:00 7:02 7:04 7:06 7:08.
    # Comparando contra la ultima CONSERVADA sobreviven 7:00 y 7:06.
    marcas = _m((7, 0), (7, 2), (7, 4), (7, 6), (7, 8))
    assert n.deduplicar(marcas) == [
        datetime(2026, 7, 30, 7, 0), datetime(2026, 7, 30, 7, 6),
    ]


def test_deduplicar_ordena_marcas_desordenadas():
    marcas = _m((13, 0), (7, 0))
    assert n.deduplicar(marcas) == [
        datetime(2026, 7, 30, 7, 0), datetime(2026, 7, 30, 13, 0),
    ]


def test_deduplicar_lista_vacia():
    assert n.deduplicar([]) == []


# -- Clasificacion de marca unica ---------------------------------------------

def test_marca_unica_cerca_del_inicio_es_entrada():
    e = n.normalizar(_m((7, 13)), JORNADA_7_A_13)
    assert e.entrada == datetime(2026, 7, 30, 7, 13)
    assert e.salida is None
    assert n.INCIDENCIA_FALTA_SALIDA in e.incidencias


def test_marca_unica_cerca_del_fin_es_salida():
    e = n.normalizar(_m((12, 59)), JORNADA_7_A_13)
    assert e.entrada is None
    assert e.salida == datetime(2026, 7, 30, 12, 59)
    assert n.INCIDENCIA_FALTA_ENTRADA in e.incidencias


def test_empate_exacto_entre_inicio_y_fin_se_resuelve_como_salida():
    # 10:00 esta a 3 h de las 7:00 y a 3 h de las 13:00.
    e = n.normalizar(_m((10, 0)), JORNADA_7_A_13)
    assert e.entrada is None
    assert e.salida == datetime(2026, 7, 30, 10, 0)
    assert n.INCIDENCIA_FALTA_ENTRADA in e.incidencias


# -- Jornada normal -----------------------------------------------------------

def test_dos_marcas_dan_entrada_y_salida_sin_incidencias():
    e = n.normalizar(_m((7, 1), (13, 2)), JORNADA_7_A_13)
    assert e.entrada == datetime(2026, 7, 30, 7, 1)
    assert e.salida == datetime(2026, 7, 30, 13, 2)
    assert e.incidencias == ()


def test_dia_sin_marcaciones_ni_correccion_no_tiene_extremos():
    e = n.normalizar([], JORNADA_7_A_13)
    assert e.entrada is None
    assert e.salida is None
    assert e.incidencias == ()


# -- Marcacion cruzada entre relojes ------------------------------------------

def test_entrada_de_un_reloj_y_salida_del_otro_es_una_jornada_normal():
    # normalizar() no conoce el equipo de origen: las marcas de los dos relojes
    # llegan en la misma lista.
    e = n.normalizar(_m((7, 21), (13, 36)), JORNADA_7_A_13)
    assert e.entrada == datetime(2026, 7, 30, 7, 21)
    assert e.salida == datetime(2026, 7, 30, 13, 36)
    assert e.incidencias == ()


def test_dos_relojes_a_tres_minutos_colapsan_en_vez_de_dar_jornada_corta():
    # El empleado ficha en los dos lectores al llegar. Sin dedup global esto
    # daria una jornada de tres minutos con la deuda completa.
    e = n.normalizar(_m((7, 0), (7, 3)), JORNADA_7_A_13)
    assert e.entrada == datetime(2026, 7, 30, 7, 0)
    assert e.salida is None
    assert e.descartadas == 1
    assert n.INCIDENCIA_FALTA_SALIDA in e.incidencias
    assert n.INCIDENCIA_REBOTE in e.incidencias


# -- Sin cronograma -----------------------------------------------------------

def test_sin_horario_emite_incidencia_y_no_clasifica():
    e = n.normalizar(_m((7, 0), (13, 0)), None)
    assert n.INCIDENCIA_SIN_CRONOGRAMA in e.incidencias
    assert e.entrada == datetime(2026, 7, 30, 7, 0)
    assert e.salida == datetime(2026, 7, 30, 13, 0)


def test_sin_horario_con_una_sola_marca_no_infiere_salida():
    e = n.normalizar(_m((7, 0)), None)
    assert e.entrada == datetime(2026, 7, 30, 7, 0)
    assert e.salida is None
    assert n.INCIDENCIA_SIN_CRONOGRAMA in e.incidencias


# -- Correccion de RRHH -------------------------------------------------------

def test_la_salida_manual_limpia_la_incidencia_de_falta_salida():
    e = n.normalizar(
        _m((7, 13)), JORNADA_7_A_13,
        n.Correccion(salida=datetime(2026, 7, 30, 13, 0)),
    )
    assert e.salida == datetime(2026, 7, 30, 13, 0)
    assert e.salida_manual is True
    assert n.INCIDENCIA_FALTA_SALIDA not in e.incidencias


def test_la_entrada_manual_limpia_la_incidencia_de_falta_entrada():
    e = n.normalizar(
        _m((12, 59)), JORNADA_7_A_13,
        n.Correccion(entrada=datetime(2026, 7, 30, 7, 0)),
    )
    assert e.entrada == datetime(2026, 7, 30, 7, 0)
    assert e.entrada_manual is True
    assert n.INCIDENCIA_FALTA_ENTRADA not in e.incidencias


def test_la_correccion_pisa_lo_que_dice_el_reloj():
    e = n.normalizar(
        _m((7, 0), (13, 0)), JORNADA_7_A_13,
        n.Correccion(entrada=datetime(2026, 7, 30, 9, 0)),
    )
    assert e.entrada == datetime(2026, 7, 30, 9, 0)
    assert e.salida == datetime(2026, 7, 30, 13, 0)
    assert e.entrada_manual is True
    assert e.salida_manual is False


def test_sin_cronograma_sobrevive_a_la_correccion():
    # La correccion aporta los extremos, pero el empleado sigue sin horario.
    e = n.normalizar(
        [], None,
        n.Correccion(entrada=datetime(2026, 7, 30, 7, 0),
                     salida=datetime(2026, 7, 30, 13, 0)),
    )
    assert n.INCIDENCIA_SIN_CRONOGRAMA in e.incidencias
