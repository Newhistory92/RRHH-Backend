"""
Tests de la herramienta de tardanzas del chatbot de RRHH.

El chatbot antes no tenia forma de responder "estadisticas de tardanzas de
tal empleado": no habia tool que leyera JornadaDiaria. Estos tests cubren la
funcion pura que arma esa respuesta, sin pasar por Gemini.
"""

from datetime import date, datetime

from tests.fakes import FakeSession

from app.routes import chat as c

FRAG_EMPLEADO = "FROM Employee WHERE name LIKE"
FRAG_HORARIO = "JOIN Horario h ON e.cronogramaId = h.id"
FRAG_JORNADAS = "FROM JornadaDiaria"


def _sesion(empleados, horario=None, jornadas=None) -> FakeSession:
    respuestas = {FRAG_EMPLEADO: empleados}
    if horario is not None:
        respuestas[FRAG_HORARIO] = horario
    if jornadas is not None:
        respuestas[FRAG_JORNADAS] = jornadas
    return FakeSession(respuestas)


# -- Resolucion de empleado ----------------------------------------------------

def test_nombre_que_no_coincide_con_nadie_da_error():
    db = _sesion(empleados=[])
    r = c._tardanzas_empleado(db, "NoExiste")
    assert "error" in r
    assert "NoExiste" in r["error"]


def test_nombre_ambiguo_no_elige_por_su_cuenta():
    db = _sesion(empleados=[
        {"id": 13, "name": "Emiliano Rojo"},
        {"id": 21, "name": "Emiliano Rojas"},
    ])
    r = c._tardanzas_empleado(db, "Emiliano Ro")
    assert r["ambiguo"] is True
    assert len(r["coincidencias"]) == 2
    # No debe haber intentado consultar horario ni jornadas de nadie.
    assert FRAG_HORARIO not in db.sql_ejecutado()
    assert FRAG_JORNADAS not in db.sql_ejecutado()


def test_empleado_sin_horario_asignado_da_error_explicito():
    db = _sesion(empleados=[{"id": 13, "name": "Emiliano Rojo"}], horario=[])
    r = c._tardanzas_empleado(db, "Emiliano Rojo")
    assert "error" in r
    assert r["empleado"]["id"] == 13
    assert FRAG_JORNADAS not in db.sql_ejecutado()


# -- Calculo de tardanzas -------------------------------------------------------

def _jornada(dia, hora, minuto, tolerancia_usada, abuso=False):
    return {
        "fecha": date(2026, 8, dia),
        "entrada": datetime(2026, 8, dia, hora, minuto),
        "toleranciaEntradaUsada": tolerancia_usada,
        "abusoEntrada": abuso,
    }


def test_llegar_antes_de_hora_no_cuenta_como_tardanza():
    db = _sesion(
        empleados=[{"id": 13, "name": "Emiliano Rojo"}],
        horario=[{"horaInicio": 8.0}],
        jornadas=[_jornada(1, 7, 55, False)],
    )
    r = c._tardanzas_empleado(db, "Emiliano Rojo")
    assert r["totalTardanzas"] == 0
    assert r["jornadasConMarcacion"] == 1


def test_cuenta_tardanzas_dentro_y_fuera_del_margen_por_separado():
    db = _sesion(
        empleados=[{"id": 13, "name": "Emiliano Rojo"}],
        horario=[{"horaInicio": 8.0}],
        jornadas=[
            _jornada(1, 8, 10, tolerancia_usada=True),   # perdonada
            _jornada(2, 8, 30, tolerancia_usada=False),  # fuera de margen
            _jornada(3, 8, 0, tolerancia_usada=False),   # puntual, no es tardanza
        ],
    )
    r = c._tardanzas_empleado(db, "Emiliano Rojo")
    assert r["totalTardanzas"] == 2
    assert r["tardanzasDentroDelMargen"] == 1
    assert r["tardanzasFueraDelMargen"] == 1


def test_promedio_de_minutos_tarde():
    db = _sesion(
        empleados=[{"id": 13, "name": "Emiliano Rojo"}],
        horario=[{"horaInicio": 8.0}],
        jornadas=[
            _jornada(1, 8, 10, True),
            _jornada(2, 8, 20, True),
        ],
    )
    r = c._tardanzas_empleado(db, "Emiliano Rojo")
    assert r["promedioMinutosTarde"] == 15.0


def test_sin_tardanzas_el_promedio_es_cero_y_no_rompe():
    db = _sesion(
        empleados=[{"id": 13, "name": "Emiliano Rojo"}],
        horario=[{"horaInicio": 8.0}],
        jornadas=[_jornada(1, 7, 55, False)],
    )
    r = c._tardanzas_empleado(db, "Emiliano Rojo")
    assert r["promedioMinutosTarde"] == 0.0
    assert r["peoresJornadas"] == []


def test_peores_jornadas_ordenadas_de_mayor_a_menor_y_topeadas_en_10():
    jornadas = [_jornada(d, 8, d, True) for d in range(1, 13)]  # 12 tardanzas
    db = _sesion(
        empleados=[{"id": 13, "name": "Emiliano Rojo"}],
        horario=[{"horaInicio": 8.0}],
        jornadas=jornadas,
    )
    r = c._tardanzas_empleado(db, "Emiliano Rojo")
    assert r["totalTardanzas"] == 12
    assert len(r["peoresJornadas"]) == 10
    minutos = [p["minutosTarde"] for p in r["peoresJornadas"]]
    assert minutos == sorted(minutos, reverse=True)
    assert minutos[0] == 12  # el dia 12 llego 8:12, el mas tarde


def test_el_periodo_devuelto_respeta_los_dias_pedidos():
    db = _sesion(
        empleados=[{"id": 13, "name": "Emiliano Rojo"}],
        horario=[{"horaInicio": 8.0}],
        jornadas=[],
    )
    r = c._tardanzas_empleado(db, "Emiliano Rojo", dias=30, hoy=date(2026, 8, 31))
    assert r["periodo"] == {"desde": "2026-08-01", "hasta": "2026-08-31"}


# -- Dispatcher -----------------------------------------------------------------

def test_ejecutar_tool_enruta_a_estadisticas_tardanzas():
    db = _sesion(
        empleados=[{"id": 13, "name": "Emiliano Rojo"}],
        horario=[{"horaInicio": 8.0}],
        jornadas=[],
    )
    r = c.ejecutar_tool("estadisticas_tardanzas", {"nombre": "Emiliano Rojo"}, db)
    assert r["empleado"]["id"] == 13
