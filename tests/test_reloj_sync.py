from datetime import datetime, timedelta

from app.services import reloj_sync as s

PAYLOAD_MIXTO = {
    "AcsEvent": {
        "searchID": "1",
        "totalMatches": 4,
        "responseStatusStrg": "MORE",
        "numOfMatches": 4,
        "InfoList": [
            {"major": 5, "minor": 21, "time": "2026-07-28T05:52:25-03:00",
             "serialNo": 168410, "currentVerifyMode": "invalid"},
            {"major": 5, "minor": 38, "time": "2026-07-28T06:08:29-03:00",
             "name": "Zalazar Beatriz", "employeeNoString": "50",
             "serialNo": 168409, "currentVerifyMode": "fpOrface"},
            {"major": 5, "minor": 22, "time": "2026-07-28T05:52:30-03:00",
             "serialNo": 168411, "currentVerifyMode": "invalid"},
            {"major": 5, "minor": 38, "time": "2026-07-28T13:02:22-03:00",
             "employeeNoString": "", "serialNo": 168500},
        ],
    }
}


def test_ventana_con_solape_de_diez_minutos():
    ultima = datetime(2026, 7, 28, 10, 0, 0)
    ahora = datetime(2026, 7, 28, 10, 5, 0)
    desde, hasta = s.calcular_ventana(ultima, ahora)
    assert desde == datetime(2026, 7, 28, 9, 50, 0)
    assert hasta == ahora


def test_primera_sync_trae_el_ultimo_mes():
    ahora = datetime(2026, 7, 29, 12, 0, 0)
    desde, hasta = s.calcular_ventana(None, ahora)
    assert desde == ahora - timedelta(days=30)
    assert hasta == ahora


def test_descarta_ruido_de_puerta_y_eventos_sin_persona():
    filas = s.extraer_marcaciones(PAYLOAD_MIXTO, "10.25.2.24")
    assert len(filas) == 1
    fila = filas[0]
    assert fila["biometricoId"] == "50"
    assert fila["serialNo"] == 168409
    assert fila["relojIp"] == "10.25.2.24"
    assert fila["nombreReloj"] == "Zalazar Beatriz"
    assert fila["verifyMode"] == "fpOrface"


# -- Modos de autenticacion ---------------------------------------------------
# Los equipos estan configurados en "fpOrface" y emiten un minor distinto segun
# como se haya identificado la persona. Capturar solo el de huella perdia el 40%
# de las marcaciones reales: sobre 2942 eventos de tres dias, minor=38 traia 723
# marcas y minor=75 (rostro) mas minor=104 aportaban otras 478 que se descartaban
# en silencio.

def _evento(minor, serial, bio="264", hora="2026-08-05T07:07:16-03:00"):
    return {"AcsEvent": {"responseStatusStrg": "OK", "numOfMatches": 1,
                         "InfoList": [{
                             "major": 5, "minor": minor, "time": hora,
                             "employeeNoString": bio, "serialNo": serial,
                             "currentVerifyMode": "fpOrface",
                         }]}}


def test_captura_la_marcacion_por_huella():
    filas = s.extraer_marcaciones(_evento(38, 187572), "10.25.2.24")
    assert [f["biometricoId"] for f in filas] == ["264"]


def test_captura_la_marcacion_por_rostro():
    # Caso real: la entrada del 2026-08-05 07:07:16 llegaba con minor=75 y se perdia.
    filas = s.extraer_marcaciones(_evento(75, 187572), "10.25.2.24")
    assert [f["biometricoId"] for f in filas] == ["264"]
    assert filas[0]["serialNo"] == 187572


def test_captura_la_marcacion_combinada():
    filas = s.extraer_marcaciones(_evento(104, 187600), "10.25.2.24")
    assert [f["biometricoId"] for f in filas] == ["264"]


def test_un_modo_desconocido_con_persona_se_registra_pero_no_se_pierde_en_silencio(caplog):
    """
    Si el equipo empieza a emitir otro minor con persona -- por ejemplo al
    habilitar tarjeta -- tiene que verse en el log. Es exactamente el modo en
    que se perdio el rostro durante semanas.
    """
    with caplog.at_level("WARNING"):
        filas = s.extraer_marcaciones(_evento(1, 190000), "10.25.2.24")

    assert filas == []
    assert "minor" in caplog.text
    assert "1" in caplog.text


def test_los_eventos_de_puerta_no_ensucian_el_log(caplog):
    """21 y 22 no traen persona: son ruido esperado, no un modo nuevo."""
    payload = {"AcsEvent": {"responseStatusStrg": "OK", "numOfMatches": 2,
                            "InfoList": [
                                {"major": 5, "minor": 21, "serialNo": 1,
                                 "time": "2026-08-05T05:52:25-03:00"},
                                {"major": 5, "minor": 22, "serialNo": 2,
                                 "time": "2026-08-05T05:52:30-03:00"},
                            ]}}
    with caplog.at_level("WARNING"):
        assert s.extraer_marcaciones(payload, "10.25.2.24") == []
    assert caplog.text == ""


def test_el_cliente_isapi_no_filtra_por_un_solo_modo():
    """
    El filtro que viaja al equipo no puede fijar un minor concreto: si lo hace,
    el equipo devuelve unicamente ese modo y los demas nunca llegan a
    extraer_marcaciones. minor=0 significa "todos" en ISAPI.
    """
    from app.services import isapi_client

    capturado = {}

    def falso_pedir(metodo, ip, path, json_body=None):
        capturado["cond"] = json_body["AcsEventCond"]
        return {"AcsEvent": {"responseStatusStrg": "OK", "numOfMatches": 0,
                             "InfoList": []}}

    original = isapi_client.pedir
    isapi_client.pedir = falso_pedir
    try:
        isapi_client.buscar_eventos(
            "10.25.2.24", datetime(2026, 8, 5, 0, 0), datetime(2026, 8, 6, 0, 0), 0,
        )
    finally:
        isapi_client.pedir = original

    assert capturado["cond"]["major"] == 5
    assert capturado["cond"]["minor"] == 0


def test_fecha_se_guarda_como_hora_local_sin_tzinfo():
    fila = s.extraer_marcaciones(PAYLOAD_MIXTO, "10.25.2.24")[0]
    assert fila["fechaHora"] == datetime(2026, 7, 28, 6, 8, 29)
    assert fila["fechaHora"].tzinfo is None


def test_payload_vacio_no_explota():
    assert s.extraer_marcaciones({}, "10.25.2.24") == []
    assert s.extraer_marcaciones({"AcsEvent": {}}, "10.25.2.24") == []


def test_deteccion_de_mas_paginas():
    assert s.hay_mas_paginas(PAYLOAD_MIXTO) is True
    assert s.hay_mas_paginas({"AcsEvent": {"responseStatusStrg": "OK"}}) is False
    assert s.hay_mas_paginas({}) is False


# -- Ventanas diarias ---------------------------------------------------------

def test_un_rango_de_un_dia_da_una_sola_ventana():
    desde = datetime(2026, 7, 30, 8, 0)
    hasta = datetime(2026, 7, 30, 20, 0)
    assert list(s.ventanas_diarias(desde, hasta)) == [(desde, hasta)]


def test_un_rango_de_tres_dias_se_parte_en_tres_ventanas():
    desde = datetime(2026, 7, 30, 8, 0)
    hasta = datetime(2026, 8, 1, 10, 0)
    ventanas = list(s.ventanas_diarias(desde, hasta))
    assert ventanas == [
        (datetime(2026, 7, 30, 8, 0), datetime(2026, 7, 31, 0, 0)),
        (datetime(2026, 7, 31, 0, 0), datetime(2026, 8, 1, 0, 0)),
        (datetime(2026, 8, 1, 0, 0), datetime(2026, 8, 1, 10, 0)),
    ]


def test_la_ventana_incremental_de_cinco_minutos_no_se_parte():
    desde = datetime(2026, 7, 30, 9, 55)
    hasta = datetime(2026, 7, 30, 10, 0)
    assert list(s.ventanas_diarias(desde, hasta)) == [(desde, hasta)]


def test_rango_invertido_no_produce_ventanas():
    desde = datetime(2026, 7, 30, 10, 0)
    hasta = datetime(2026, 7, 30, 9, 0)
    assert list(s.ventanas_diarias(desde, hasta)) == []


def test_la_carga_inicial_de_treinta_dias_da_treinta_y_un_ventanas():
    ahora = datetime(2026, 7, 30, 12, 0)
    desde, hasta = s.calcular_ventana(None, ahora)
    # 30 dias hacia atras desde el mediodia: 30 cortes de medianoche + el resto.
    assert len(list(s.ventanas_diarias(desde, hasta))) == 31


# -- Deteccion de truncamiento ------------------------------------------------

def test_el_total_declarado_sale_de_total_matches():
    assert s.total_declarado({"AcsEvent": {"totalMatches": 395}}) == 395


def test_sin_total_matches_no_hay_total_declarado():
    assert s.total_declarado({"AcsEvent": {}}) is None
    assert s.total_declarado({}) is None


def test_se_cuentan_los_eventos_realmente_entregados():
    # Lo que vale es la lista que llego, no lo que el equipo dice haber mandado.
    payload = {"AcsEvent": {"numOfMatches": 30, "InfoList": [{}, {}, {}]}}
    assert s.eventos_entregados(payload) == 3


def test_pagina_vacia_no_entrega_eventos():
    assert s.eventos_entregados({}) == 0


def test_entregar_menos_de_lo_declarado_es_ventana_incompleta():
    assert s.ventana_incompleta(254, 395) is True


def test_entregar_todo_lo_declarado_no_es_incompleto():
    assert s.ventana_incompleta(395, 395) is False


def test_sin_declaracion_no_se_puede_afirmar_que_falte():
    # Si el equipo no dice cuantos hay, no se puede acusar de incompleta una
    # ventana: se la da por buena antes que frenar el cursor para siempre.
    assert s.ventana_incompleta(0, None) is False


def test_el_guard_dispara_con_la_paginacion_real_de_los_equipos():
    # Regresion del hueco del 2026-08-05. Los equipos paginan de a 30 y
    # declaran 395; la heuristica vieja comparaba numOfMatches contra
    # MAX_RESULTS=100, un valor que estos relojes no emiten nunca, asi que no
    # podia dispararse y el cursor avanzaba por encima del hueco.
    pagina = {"AcsEvent": {"responseStatusStrg": "OK", "numOfMatches": 30,
                           "totalMatches": 395, "InfoList": [{}] * 30}}
    assert s.ventana_incompleta(
        s.eventos_entregados(pagina), s.total_declarado(pagina)) is True
