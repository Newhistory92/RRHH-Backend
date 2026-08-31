from datetime import date, datetime

from app.services import asistencia_calc as c
from app.services import marcaciones_norm as n

JORNADA_8H = n.HorarioDia(horaInicio=8.0, horaFin=16.0, horasTrabajo=8.0)
TOL = c.Tolerancias(entradaMin=15, salidaMin=15,
                    estrictaEntradaMin=7, estrictaSalidaMin=5)


def _dia(fecha=date(2026, 7, 1), marcaciones=None, horario=JORNADA_8H,
         es_feriado=False, tiene_licencia=False, permisos=None,
         entrada_manual=None, salida_manual=None, justificada=False):
    """
    Miercoles 2026-07-01 por defecto: dia habil.

    Arma los extremos pasando por normalizar(), asi los tests del motor
    ejercitan la misma cadena que produccion.
    """
    correccion = None
    if entrada_manual is not None or salida_manual is not None:
        correccion = n.Correccion(entrada=entrada_manual, salida=salida_manual)
    return c.EntradaDia(
        fecha=fecha,
        extremos=n.normalizar(
            marcaciones if marcaciones is not None else [], horario, correccion,
        ),
        horario=horario,
        es_feriado=es_feriado,
        tiene_licencia=tiene_licencia,
        permisos=permisos if permisos is not None else [],
        justificada=justificada,
    )


def _marcas(*horas):
    return [datetime(2026, 7, 1, h, m) for h, m in horas]


# -- Tolerancia ---------------------------------------------------------------

def test_llegar_dentro_de_la_tolerancia_no_penaliza():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (16, 0))), TOL, 12.0)
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0
    assert r.estado == c.ESTADO_OK


def test_pasada_la_tolerancia_se_descuenta_todo_el_atraso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 20), (16, 0))), TOL, 12.0)
    # round() evita diferencias de punto flotante en la resta de horas decimales
    assert round(r.horasTrabajadas, 4) == round(7.0 + 40 / 60, 4)
    assert round(r.saldoDia, 4) == round(-20 / 60, 4)


def test_salir_dentro_de_la_tolerancia_no_penaliza():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (15, 50))), TOL, 12.0)
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_las_dos_tolerancias_se_aplican_por_separado():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (15, 50))), TOL, 12.0)
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_entrada_anticipada_y_salida_tardia_suman_a_favor():
    r = c.calcular_dia(_dia(marcaciones=_marcas((7, 50), (16, 10))), TOL, 12.0)
    assert round(r.horasTrabajadas, 4) == round(8.0 + 20 / 60, 4)
    assert round(r.saldoDia, 4) == round(20 / 60, 4)


# -- La tolerancia perdona la deuda, pero no la convierte en credito ----------

def test_la_salida_tardia_no_cobra_como_extra_la_entrada_tarde_perdonada():
    """
    Entra 8:10 (10 min tarde, perdonados) y se va 16:08 (8 min de mas).

    Los 8 minutos extra se los come el atraso de la entrada: no alcanzan a
    cubrirlo entero, pero la tolerancia evita el saldo negativo. Antes la
    entrada se movia a las 8:00 y los 8 minutos quedaban como saldo a favor,
    o sea que llegar tarde pagaba mejor que llegar puntual.
    """
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (16, 8))), TOL, 12.0)
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_el_excedente_que_supera_el_atraso_perdonado_si_queda_a_favor():
    """Entra 8:10 y se va 16:30: 30 min extra menos 10 de atraso = 20 a favor."""
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (16, 30))), TOL, 12.0)
    assert round(r.horasTrabajadas, 4) == round(8.0 + 20 / 60, 4)
    assert round(r.saldoDia, 4) == round(20 / 60, 4)


def test_caso_real_jornada_de_6_horas_entrada_711_salida_1308():
    """Caso reportado en produccion: horario 7 a 13, entra 7:11 y sale 13:08."""
    horario = n.HorarioDia(horaInicio=7.0, horaFin=13.0, horasTrabajo=6.0)
    r = c.calcular_dia(
        _dia(horario=horario, marcaciones=_marcas((7, 11), (13, 8))), TOL, 12.0,
    )
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == 0.0


def test_el_limite_exacto_de_la_tolerancia_todavia_perdona():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 15), (16, 0))), TOL, 12.0)
    assert r.saldoDia == 0.0


def test_un_minuto_pasada_la_tolerancia_ya_penaliza():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 16), (16, 0))), TOL, 12.0)
    assert round(r.saldoDia, 4) == round(-16 / 60, 4)


# -- Segundo umbral: abuso de la tolerancia ----------------------------------

def test_entrada_dentro_del_margen_estricto_no_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 5), (16, 0))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is True
    assert r.abusoEntrada is False


def test_entrada_justo_en_el_umbral_estricto_no_es_abuso():
    # 8:07:00 exacto: el borde es indulgente, igual que el de 15 minutos.
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 7), (16, 0))), TOL, 12.0)
    assert r.abusoEntrada is False


def test_entrada_un_segundo_pasado_el_umbral_estricto_es_abuso():
    dia = _dia(marcaciones=[datetime(2026, 7, 1, 8, 7, 1),
                            datetime(2026, 7, 1, 16, 0)])
    r = c.calcular_dia(dia, TOL, 12.0)
    assert r.toleranciaEntradaUsada is True
    assert r.abusoEntrada is True
    assert r.saldoDia == 0.0  # el abuso no descuenta horas


def test_entrada_en_el_limite_de_la_tolerancia_comun_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 15), (16, 0))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is True
    assert r.abusoEntrada is True


def test_entrada_pasada_la_tolerancia_comun_no_es_abuso_porque_ya_se_descuenta():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 16), (16, 0))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is False
    assert r.abusoEntrada is False
    assert r.saldoDia < 0


def test_llegar_antes_de_hora_no_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((7, 50), (16, 0))), TOL, 12.0)
    assert r.abusoEntrada is False


def test_salida_dentro_del_margen_estricto_no_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (15, 56))), TOL, 12.0)
    assert r.toleranciaSalidaUsada is True
    assert r.abusoSalida is False


def test_salida_pasada_el_margen_estricto_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (15, 54))), TOL, 12.0)
    assert r.toleranciaSalidaUsada is True
    assert r.abusoSalida is True
    assert r.saldoDia == 0.0


def test_salir_despues_de_hora_no_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (16, 5))), TOL, 12.0)
    assert r.abusoSalida is False


def test_los_dos_extremos_pueden_abusar_el_mismo_dia():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 12), (15, 52))), TOL, 12.0)
    assert r.abusoEntrada is True
    assert r.abusoSalida is True


def test_un_horario_que_no_arranca_en_hora_redonda_respeta_el_borde_exacto():
    """
    El desvio se compara en segundos enteros justamente para este caso: en
    horas decimales 7.5 + 7/60 y _hora_decimal(7:37:00) son la misma cantidad
    matematica pero pueden diferir en el ultimo bit del float.
    """
    horario = n.HorarioDia(horaInicio=7.5, horaFin=15.5, horasTrabajo=8.0)
    dia = _dia(horario=horario,
               marcaciones=[datetime(2026, 7, 1, 7, 37, 0),
                            datetime(2026, 7, 1, 15, 30)])
    r = c.calcular_dia(dia, TOL, 12.0)
    assert r.abusoEntrada is False


def test_los_dias_sin_jornada_calculada_no_marcan_abuso():
    ausente = c.calcular_dia(_dia(), TOL, 12.0)
    assert (ausente.abusoEntrada, ausente.abusoSalida) == (False, False)

    incompleta = c.calcular_dia(_dia(marcaciones=_marcas((8, 10))), TOL, 12.0)
    assert (incompleta.abusoEntrada, incompleta.abusoSalida) == (False, False)

    licencia = c.calcular_dia(_dia(tiene_licencia=True), TOL, 12.0)
    assert (licencia.abusoEntrada, licencia.abusoSalida) == (False, False)

    sin_horario = c.calcular_dia(_dia(horario=None), TOL, 12.0)
    assert (sin_horario.abusoEntrada, sin_horario.abusoSalida) == (False, False)

    feriado = c.calcular_dia(
        _dia(es_feriado=True, marcaciones=_marcas((8, 10), (16, 0))), TOL, 12.0,
    )
    assert (feriado.abusoEntrada, feriado.abusoSalida) == (False, False)


# -- Permisos y banco anual ---------------------------------------------------

def test_permiso_dentro_del_banco_deja_saldo_cero():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, False)]),
        TOL, 12.0,
    )
    assert r.horasRequeridas == 6.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == 0.0
    assert r.permisoBanco == 2.0
    assert r.permisoDeuda == 0.0


def test_permiso_con_banco_agotado_genera_deuda_completa():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, False)]),
        TOL, 0.0,
    )
    assert r.horasRequeridas == 8.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == -2.0
    assert r.permisoBanco == 0.0
    assert r.permisoDeuda == 2.0


def test_banco_partido_al_medio_debe_solo_el_excedente():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, False)]),
        TOL, 1.0,
    )
    assert r.horasRequeridas == 7.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == -1.0
    assert r.permisoBanco == 1.0
    assert r.permisoDeuda == 1.0


def test_permiso_oficial_es_neutro_y_no_consume_banco():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, True)]),
        TOL, 0.0,
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
        TOL, 12.0,
    )
    assert r.horasRequeridas == 0.0


def test_el_banco_se_arrastra_cronologicamente_en_el_anio():
    dias = [
        _dia(fecha=date(2026, 1, 7), marcaciones=_marcas((8, 0), (16, 0)),
             permisos=[c.Permiso(8.0, False)]),
        _dia(fecha=date(2026, 2, 4), marcaciones=_marcas((8, 0), (16, 0)),
             permisos=[c.Permiso(8.0, False)]),
    ]
    enero, febrero = c.calcular_anio(dias, TOL)
    assert enero.permisoBanco == 8.0
    assert enero.permisoDeuda == 0.0
    assert enero.saldoDia == 0.0
    # Del segundo permiso solo quedan 4 h de banco: las otras 4 son deuda.
    assert febrero.permisoBanco == 4.0
    assert febrero.permisoDeuda == 4.0
    assert febrero.saldoDia == -4.0


# -- Estados especiales -------------------------------------------------------

def test_una_sola_marcacion_queda_incompleta_sin_penalizar():
    # 8:00 esta mas cerca del inicio (8.0) que del fin (16.0): es entrada.
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0))), TOL, 12.0)
    assert r.estado == c.ESTADO_INCOMPLETA
    assert r.saldoDia == 0.0
    assert r.entrada == datetime(2026, 7, 1, 8, 0)
    assert r.salida is None
    assert n.INCIDENCIA_FALTA_SALIDA in r.incidencias


def test_sin_marcaciones_en_dia_habil_es_ausente():
    r = c.calcular_dia(_dia(), TOL, 12.0)
    assert r.estado == c.ESTADO_AUSENTE
    assert r.horasRequeridas == 8.0
    assert r.horasTrabajadas == 0.0
    assert r.saldoDia == -8.0


def test_licencia_aprobada_neutraliza_el_dia():
    r = c.calcular_dia(_dia(tiene_licencia=True), TOL, 12.0)
    assert r.estado == c.ESTADO_LICENCIA
    assert r.saldoDia == 0.0


def test_sin_horario_no_genera_deuda():
    r = c.calcular_dia(_dia(horario=None), TOL, 12.0)
    assert r.estado == c.ESTADO_SIN_HORARIO
    assert r.saldoDia == 0.0


def test_fin_de_semana_sin_marcaciones_no_genera_fila():
    # 2026-07-04 es sabado
    assert c.calcular_dia(_dia(fecha=date(2026, 7, 4)), TOL, 12.0) is None


def test_feriado_sin_marcaciones_no_genera_fila():
    assert c.calcular_dia(_dia(es_feriado=True), TOL, 12.0) is None


def test_feriado_trabajado_suma_todo_a_favor_sin_tolerancia():
    r = c.calcular_dia(
        _dia(es_feriado=True, marcaciones=_marcas((8, 10), (16, 0))), TOL, 12.0,
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
        TOL, 12.0,
    )
    assert r.estado == c.ESTADO_OK
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_la_entrada_manual_pisa_la_primera_marcacion():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)),
             entrada_manual=datetime(2026, 7, 1, 9, 0)),
        TOL, 12.0,
    )
    assert r.entrada == datetime(2026, 7, 1, 9, 0)
    assert r.horasTrabajadas == 7.0


# -- Flags de tolerancia ------------------------------------------------------

def test_flag_de_tolerancia_de_entrada_cuando_se_aplica():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (16, 0))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is True
    assert r.toleranciaSalidaUsada is False


def test_flag_de_tolerancia_de_salida_cuando_se_aplica():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (15, 50))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is False
    assert r.toleranciaSalidaUsada is True


def test_ambas_tolerancias_marcadas():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (15, 50))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is True
    assert r.toleranciaSalidaUsada is True


def test_ninguna_tolerancia_cuando_llega_puntual():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (16, 0))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is False
    assert r.toleranciaSalidaUsada is False


def test_pasada_la_tolerancia_el_flag_queda_en_falso():
    # 8:20 supera los 15 min: no se perdona, asi que la tolerancia no se "uso".
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 20), (16, 0))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is False


# -- Incidencias y flags manuales ---------------------------------------------

def test_las_incidencias_llegan_al_resultado():
    r = c.calcular_dia(_dia(horario=None), TOL, 12.0)
    assert n.INCIDENCIA_SIN_CRONOGRAMA in r.incidencias


def test_los_flags_manuales_llegan_al_resultado():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0)), salida_manual=datetime(2026, 7, 1, 16, 0)),
        TOL, 12.0,
    )
    assert r.entradaManual is False
    assert r.salidaManual is True


def test_jornada_normal_no_tiene_incidencias():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (16, 0))), TOL, 12.0)
    assert r.incidencias == ()


# -- Justificacion de ausencias -----------------------------------------------

def test_ausencia_justificada_no_resta_horas():
    r = c.calcular_dia(_dia(justificada=True), TOL, 12.0)
    assert r.estado == c.ESTADO_JUSTIFICADA
    assert r.horasRequeridas == 0.0
    assert r.horasTrabajadas == 0.0
    assert r.saldoDia == 0.0


def test_ausencia_sin_justificar_sigue_restando_la_jornada():
    r = c.calcular_dia(_dia(), TOL, 12.0)
    assert r.estado == c.ESTADO_AUSENTE
    assert r.horasRequeridas == 8.0
    assert r.saldoDia == -8.0


def test_la_justificacion_no_borra_las_horas_realmente_trabajadas():
    # Si aparece una marcacion despues de justificar, la persona trabajo:
    # se le cuentan las horas y el dia no queda como justificado.
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), justificada=True), TOL, 12.0,
    )
    assert r.estado == c.ESTADO_OK
    assert r.horasTrabajadas == 8.0


def test_con_licencia_y_justificacion_gana_la_licencia():
    r = c.calcular_dia(_dia(tiene_licencia=True, justificada=True), TOL, 12.0)
    assert r.estado == c.ESTADO_LICENCIA


def test_un_dia_no_laborable_justificado_sigue_sin_generar_fila():
    # Sabado 2026-07-04.
    r = c.calcular_dia(_dia(fecha=date(2026, 7, 4), justificada=True), TOL, 12.0)
    assert r is None


def test_una_jornada_incompleta_justificada_sigue_incompleta():
    # Falta un extremo: no es una ausencia, asi que la justificacion no aplica.
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0)), justificada=True), TOL, 12.0,
    )
    assert r.estado == c.ESTADO_INCOMPLETA
