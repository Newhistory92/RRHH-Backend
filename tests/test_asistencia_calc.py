from datetime import date, datetime

from app.services import asistencia_calc as c

JORNADA_8H = c.HorarioDia(horaInicio=8.0, horaFin=16.0, horasTrabajo=8.0)


def _dia(fecha=date(2026, 7, 1), marcaciones=None, horario=JORNADA_8H,
         es_feriado=False, tiene_licencia=False, permisos=None,
         entrada_manual=None, salida_manual=None):
    """Miercoles 2026-07-01 por defecto: dia habil."""
    return c.EntradaDia(
        fecha=fecha,
        marcaciones=marcaciones if marcaciones is not None else [],
        horario=horario,
        es_feriado=es_feriado,
        tiene_licencia=tiene_licencia,
        permisos=permisos if permisos is not None else [],
        entrada_manual=entrada_manual,
        salida_manual=salida_manual,
    )


def _marcas(*horas):
    return [datetime(2026, 7, 1, h, m) for h, m in horas]


# -- Tolerancia ---------------------------------------------------------------

def test_llegar_dentro_de_la_tolerancia_no_penaliza():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (16, 0))), 15, 15, 12.0)
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0
    assert r.estado == c.ESTADO_OK


def test_pasada_la_tolerancia_se_descuenta_todo_el_atraso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 20), (16, 0))), 15, 15, 12.0)
    # round() evita diferencias de punto flotante en la resta de horas decimales
    assert round(r.horasTrabajadas, 4) == round(7.0 + 40 / 60, 4)
    assert round(r.saldoDia, 4) == round(-20 / 60, 4)


def test_salir_dentro_de_la_tolerancia_no_penaliza():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (15, 50))), 15, 15, 12.0)
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_las_dos_tolerancias_se_aplican_por_separado():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (15, 50))), 15, 15, 12.0)
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_entrada_anticipada_y_salida_tardia_suman_a_favor():
    r = c.calcular_dia(_dia(marcaciones=_marcas((7, 50), (16, 10))), 15, 15, 12.0)
    assert round(r.horasTrabajadas, 4) == round(8.0 + 20 / 60, 4)
    assert round(r.saldoDia, 4) == round(20 / 60, 4)


def test_el_limite_exacto_de_la_tolerancia_todavia_perdona():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 15), (16, 0))), 15, 15, 12.0)
    assert r.saldoDia == 0.0


def test_un_minuto_pasada_la_tolerancia_ya_penaliza():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 16), (16, 0))), 15, 15, 12.0)
    assert round(r.saldoDia, 4) == round(-16 / 60, 4)


# -- Permisos y banco anual ---------------------------------------------------

def test_permiso_dentro_del_banco_deja_saldo_cero():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, False)]),
        15, 15, 12.0,
    )
    assert r.horasRequeridas == 6.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == 0.0
    assert r.permisoBanco == 2.0
    assert r.permisoDeuda == 0.0


def test_permiso_con_banco_agotado_genera_deuda_completa():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, False)]),
        15, 15, 0.0,
    )
    assert r.horasRequeridas == 8.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == -2.0
    assert r.permisoBanco == 0.0
    assert r.permisoDeuda == 2.0


def test_banco_partido_al_medio_debe_solo_el_excedente():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, False)]),
        15, 15, 1.0,
    )
    assert r.horasRequeridas == 7.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == -1.0
    assert r.permisoBanco == 1.0
    assert r.permisoDeuda == 1.0


def test_permiso_oficial_es_neutro_y_no_consume_banco():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, True)]),
        15, 15, 0.0,
    )
    assert r.horasRequeridas == 6.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == 0.0
    assert r.permisoOficial == 2.0
    assert r.permisoBanco == 0.0
    assert r.permisoDeuda == 0.0


def test_permiso_mayor_a_la_jornada_trunca_requeridas_en_cero():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(10.0, True)]),
        15, 15, 12.0,
    )
    assert r.horasRequeridas == 0.0


def test_el_banco_se_arrastra_cronologicamente_en_el_anio():
    dias = [
        _dia(fecha=date(2026, 1, 7), marcaciones=_marcas((8, 0), (16, 0)),
             permisos=[c.Permiso(8.0, False)]),
        _dia(fecha=date(2026, 2, 4), marcaciones=_marcas((8, 0), (16, 0)),
             permisos=[c.Permiso(8.0, False)]),
    ]
    enero, febrero = c.calcular_anio(dias, 15, 15)
    assert enero.permisoBanco == 8.0
    assert enero.permisoDeuda == 0.0
    assert enero.saldoDia == 0.0
    # Del segundo permiso solo quedan 4 h de banco: las otras 4 son deuda.
    assert febrero.permisoBanco == 4.0
    assert febrero.permisoDeuda == 4.0
    assert febrero.saldoDia == -4.0


# -- Estados especiales -------------------------------------------------------

def test_una_sola_marcacion_queda_incompleta_sin_penalizar():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0))), 15, 15, 12.0)
    assert r.estado == c.ESTADO_INCOMPLETA
    assert r.saldoDia == 0.0
    assert r.entrada == datetime(2026, 7, 1, 8, 0)
    assert r.salida is None


def test_sin_marcaciones_en_dia_habil_es_ausente():
    r = c.calcular_dia(_dia(), 15, 15, 12.0)
    assert r.estado == c.ESTADO_AUSENTE
    assert r.horasRequeridas == 8.0
    assert r.horasTrabajadas == 0.0
    assert r.saldoDia == -8.0


def test_licencia_aprobada_neutraliza_el_dia():
    r = c.calcular_dia(_dia(tiene_licencia=True), 15, 15, 12.0)
    assert r.estado == c.ESTADO_LICENCIA
    assert r.saldoDia == 0.0


def test_sin_horario_no_genera_deuda():
    r = c.calcular_dia(_dia(horario=None), 15, 15, 12.0)
    assert r.estado == c.ESTADO_SIN_HORARIO
    assert r.saldoDia == 0.0


def test_fin_de_semana_sin_marcaciones_no_genera_fila():
    # 2026-07-04 es sabado
    assert c.calcular_dia(_dia(fecha=date(2026, 7, 4)), 15, 15, 12.0) is None


def test_feriado_sin_marcaciones_no_genera_fila():
    assert c.calcular_dia(_dia(es_feriado=True), 15, 15, 12.0) is None


def test_feriado_trabajado_suma_todo_a_favor_sin_tolerancia():
    r = c.calcular_dia(
        _dia(es_feriado=True, marcaciones=_marcas((8, 10), (16, 0))), 15, 15, 12.0,
    )
    assert r.estado == c.ESTADO_FERIADO
    assert r.horasRequeridas == 0.0
    # Sin tolerancia: cuenta el tiempo real, 8:10 a 16:00.
    assert round(r.horasTrabajadas, 4) == round(7.0 + 50 / 60, 4)
    assert round(r.saldoDia, 4) == round(7.0 + 50 / 60, 4)


# -- Carga manual de RRHH -----------------------------------------------------

def test_la_salida_manual_completa_una_jornada_incompleta():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0)), salida_manual=datetime(2026, 7, 1, 16, 0)),
        15, 15, 12.0,
    )
    assert r.estado == c.ESTADO_OK
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_la_entrada_manual_pisa_la_primera_marcacion():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)),
             entrada_manual=datetime(2026, 7, 1, 9, 0)),
        15, 15, 12.0,
    )
    assert r.entrada == datetime(2026, 7, 1, 9, 0)
    assert r.horasTrabajadas == 7.0
