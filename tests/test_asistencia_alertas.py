from datetime import date

from app.services import asistencia_alertas as a


def _dia(dia_del_mes, abuso, estado="ok"):
    return a.DiaAbuso(fecha=date(2026, 8, dia_del_mes), estado=estado, abuso=abuso)


def test_lista_vacia_no_tiene_racha_ni_alerta():
    r = a.resumir([], dias_alerta=3)
    assert r.diasAbuso == 0
    assert r.rachaMaxima == 0
    assert r.fechasRachaMaxima == ()
    assert r.alerta is False


def test_ningun_dia_con_abuso():
    r = a.resumir([_dia(3, False), _dia(4, False)], dias_alerta=3)
    assert r.diasAbuso == 0
    assert r.alerta is False


def test_tres_dias_trabajados_encadenados_disparan_la_alerta():
    r = a.resumir([_dia(3, True), _dia(4, True), _dia(5, True)], dias_alerta=3)
    assert r.diasAbuso == 3
    assert r.rachaMaxima == 3
    assert r.fechasRachaMaxima == (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5))
    assert r.alerta is True


def test_dos_dias_encadenados_no_alcanzan():
    r = a.resumir([_dia(3, True), _dia(4, True)], dias_alerta=3)
    assert r.rachaMaxima == 2
    assert r.alerta is False


def test_un_dia_trabajado_sin_abuso_corta_la_racha():
    dias = [_dia(3, True), _dia(4, True), _dia(5, False), _dia(6, True)]
    r = a.resumir(dias, dias_alerta=3)
    assert r.diasAbuso == 3
    assert r.rachaMaxima == 2
    assert r.alerta is False


def test_ausencia_licencia_e_incompleta_se_saltean_sin_cortar():
    dias = [
        _dia(3, True),
        _dia(4, False, estado="ausente"),
        _dia(5, True),
        _dia(6, False, estado="licencia"),
        _dia(7, True),
        _dia(8, False, estado="incompleta"),
    ]
    r = a.resumir(dias, dias_alerta=3)
    assert r.rachaMaxima == 3
    assert r.fechasRachaMaxima == (date(2026, 8, 3), date(2026, 8, 5), date(2026, 8, 7))
    assert r.alerta is True


def test_los_dias_no_trabajados_no_suman_al_total_aunque_traigan_el_flag():
    dias = [_dia(3, True, estado="feriado"), _dia(4, True, estado="sin_horario")]
    r = a.resumir(dias, dias_alerta=3)
    assert r.diasAbuso == 0
    assert r.rachaMaxima == 0


def test_ante_empate_gana_la_racha_mas_reciente():
    dias = [
        _dia(3, True), _dia(4, True),
        _dia(5, False),
        _dia(6, True), _dia(7, True),
    ]
    r = a.resumir(dias, dias_alerta=3)
    assert r.rachaMaxima == 2
    assert r.fechasRachaMaxima == (date(2026, 8, 6), date(2026, 8, 7))


def test_la_racha_mas_larga_gana_aunque_sea_anterior():
    dias = [
        _dia(3, True), _dia(4, True), _dia(5, True),
        _dia(6, False),
        _dia(7, True),
    ]
    r = a.resumir(dias, dias_alerta=3)
    assert r.rachaMaxima == 3
    assert r.fechasRachaMaxima == (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5))


def test_los_dias_se_ordenan_por_fecha_antes_de_recorrer():
    dias = [_dia(5, True), _dia(3, True), _dia(4, True)]
    r = a.resumir(dias, dias_alerta=3)
    assert r.fechasRachaMaxima == (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5))


def test_el_umbral_de_alerta_es_configurable():
    dias = [_dia(3, True), _dia(4, True)]
    assert a.resumir(dias, dias_alerta=2).alerta is True
    assert a.resumir(dias, dias_alerta=5).alerta is False


def test_todos_los_dias_con_abuso():
    dias = [_dia(d, True) for d in range(3, 11)]
    r = a.resumir(dias, dias_alerta=3)
    assert r.diasAbuso == 8
    assert r.rachaMaxima == 8
    assert r.alerta is True


# -- Validacion de umbrales ---------------------------------------------------

def test_umbrales_validos_no_lanzan():
    a.validar_umbrales(15, 15, 7, 5, 3)


def test_estricta_igual_a_la_comun_es_valida():
    a.validar_umbrales(15, 15, 15, 15, 3)


def test_estricta_de_entrada_mayor_que_la_comun_se_rechaza():
    try:
        a.validar_umbrales(15, 15, 16, 5, 3)
        assert False, "deberia haber lanzado ValueError"
    except ValueError as e:
        assert "toleranciaEstrictaEntradaMin" in str(e)


def test_estricta_de_salida_mayor_que_la_comun_se_rechaza():
    try:
        a.validar_umbrales(15, 15, 7, 16, 3)
        assert False, "deberia haber lanzado ValueError"
    except ValueError as e:
        assert "toleranciaEstrictaSalidaMin" in str(e)


def test_estricta_negativa_se_rechaza():
    try:
        a.validar_umbrales(15, 15, -1, 5, 3)
        assert False, "deberia haber lanzado ValueError"
    except ValueError as e:
        assert "toleranciaEstrictaEntradaMin" in str(e)


def test_dias_de_racha_fuera_de_rango_se_rechaza():
    for valor in (0, 31):
        try:
            a.validar_umbrales(15, 15, 7, 5, valor)
            assert False, f"deberia haber lanzado ValueError con {valor}"
        except ValueError as e:
            assert "diasRachaAlerta" in str(e)


def test_los_umbrales_opcionales_en_none_no_se_validan():
    a.validar_umbrales(15, 15, None, None, None)
