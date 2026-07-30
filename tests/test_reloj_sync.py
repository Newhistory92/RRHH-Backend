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
