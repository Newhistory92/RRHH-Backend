"""
Los dias en que alguien estuvo de baja no cuentan para la asistencia.

Ni suman ni restan: es como si no hubiera estado en planta. La fechaBaja es
el ultimo dia computado (igual que el corte de rango_de_calculo) y el dia de
reingreso se trabaja, asi que lo excluido es lo que queda estrictamente en el
medio. La parte pura se testea sola; recalcular_anio va con FakeSession.
"""

from datetime import date

from app.services.asistencia_recalc import _datos_empleado, recalcular_anio
from app.services.bajas import dia_excluido, intervalos_de_baja
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def _baja(fecha_baja, fecha_reingreso=None):
    return {"motivo": "Renuncia", "fechaBaja": fecha_baja,
            "fechaReingreso": fecha_reingreso}


# -- Intervalos, sin base ------------------------------------------------------

def test_sin_bajas_no_hay_nada_excluido():
    assert intervalos_de_baja([], HOY) == []


def test_una_baja_vigente_excluye_todo_lo_posterior():
    assert intervalos_de_baja([_baja(date(2026, 6, 30))], HOY) == [
        (date(2026, 7, 1), None),
    ]


def test_una_baja_programada_todavia_no_excluye_nada():
    assert intervalos_de_baja([_baja(date(2026, 12, 1))], HOY) == []


def test_una_baja_cerrada_excluye_el_hueco_y_no_el_reingreso():
    assert intervalos_de_baja([_baja(date(2026, 3, 10), date(2026, 3, 20))], HOY) == [
        (date(2026, 3, 11), date(2026, 3, 19)),
    ]


def test_reingresar_al_dia_siguiente_no_deja_hueco():
    assert intervalos_de_baja([_baja(date(2026, 3, 10), date(2026, 3, 11))], HOY) == []


def test_varias_bajas_dan_varios_intervalos_ordenados():
    bajas = [_baja(date(2026, 6, 30)), _baja(date(2026, 3, 10), date(2026, 3, 20))]
    assert intervalos_de_baja(bajas, HOY) == [
        (date(2026, 3, 11), date(2026, 3, 19)),
        (date(2026, 7, 1), None),
    ]


def test_dia_excluido_respeta_los_bordes():
    intervalos = [(date(2026, 3, 11), date(2026, 3, 19)), (date(2026, 7, 1), None)]
    assert not dia_excluido(date(2026, 3, 10), intervalos)
    assert dia_excluido(date(2026, 3, 11), intervalos)
    assert dia_excluido(date(2026, 3, 19), intervalos)
    assert not dia_excluido(date(2026, 3, 20), intervalos)
    assert not dia_excluido(date(2026, 6, 30), intervalos)
    assert dia_excluido(date(2030, 1, 1), intervalos)


# -- recalcular_anio, con FakeSession ------------------------------------------

def _db(bajas):
    return FakeSession({
        "FROM Employee e": [{
            "id": 8, "biometricoId": "123",
            "horaInicio": 8.0, "horaFin": 16.0, "horasTrabajo": 8.0,
            "fechaIngreso": date(2020, 1, 1),
            "horasPermisoAnual": 12.0,
        }],
        "FROM AsistenciaConfig": [{
            "toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
            "fechaInicioModulo": date(2026, 1, 1),
            "toleranciaEstrictaEntradaMin": 7, "toleranciaEstrictaSalidaMin": 5,
            "diasRachaAlerta": 3,
        }],
        "FROM EmployeeBaja": bajas,
    })


def _borrados(db, tabla):
    return [(p["desde"], p["hasta"]) for sql, p in db.ejecutadas
            if f"DELETE FROM {tabla}" in sql]


def _insertados(db):
    return {p["fecha"] for sql, p in db.ejecutadas
            if "INSERT INTO JornadaDiaria" in sql}


def test_una_baja_retroactiva_borra_las_jornadas_posteriores():
    """Las jornadas ya calculadas despues de la baja no pueden seguir sumando."""
    db = _db([_baja(date(2026, 6, 30))])
    recalcular_anio(db, 8, 2026, hoy=HOY)

    assert (date(2026, 7, 1), date(2026, 12, 31)) in _borrados(db, "JornadaDiaria")
    assert (date(2026, 7, 1), date(2026, 12, 31)) in _borrados(db, "JornadaIncidencia")
    insertados = _insertados(db)
    assert insertados
    assert max(insertados) <= date(2026, 6, 30)


def test_una_baja_anterior_al_anio_tambien_borra_aunque_no_haya_rango():
    db = _db([_baja(date(2025, 5, 1))])
    recalcular_anio(db, 8, 2026, hoy=HOY)

    assert (date(2026, 1, 1), date(2026, 12, 31)) in _borrados(db, "JornadaDiaria")
    assert (date(2026, 1, 1), date(2026, 12, 31)) in _borrados(db, "JornadaIncidencia")
    assert not _insertados(db)
    # El saldo cacheado se resincroniza con lo que quedo.
    assert "UPDATE Employee SET horas" in db.sql_ejecutado()
    assert db.commits >= 1


def test_una_baja_cerrada_excluye_el_hueco_y_computa_el_reingreso():
    """Sin esto el hueco se contaba como dias habiles sin marcar."""
    db = _db([_baja(date(2026, 3, 10), date(2026, 3, 20))])
    recalcular_anio(db, 8, 2026, hoy=HOY)

    insertados = _insertados(db)
    assert date(2026, 3, 10) in insertados  # martes, ultimo dia computado
    assert date(2026, 3, 20) in insertados  # viernes, el reingreso se trabaja
    assert not any(date(2026, 3, 11) <= d <= date(2026, 3, 19) for d in insertados)
    assert (date(2026, 3, 11), date(2026, 3, 19)) in _borrados(db, "JornadaDiaria")
    # Despues del reingreso se sigue computando hasta hoy.
    assert max(insertados) > date(2026, 9, 1)


def test_el_recalculo_usa_la_misma_nocion_de_baja_vigente():
    """La cota sale de baja_vigente con el hoy del recalculo: una programada
    no corta y se sigue computando hasta hoy."""
    db = _db([_baja(date(2026, 12, 1))])
    recalcular_anio(db, 8, 2026, hoy=HOY)
    assert _borrados(db, "JornadaDiaria") == [(date(2026, 1, 1), HOY)]
    assert max(_insertados(db)) <= HOY


def test_sin_bajas_no_borra_nada_fuera_del_rango():
    db = _db([])
    recalcular_anio(db, 8, 2026, hoy=HOY)
    assert _borrados(db, "JornadaDiaria") == [(date(2026, 1, 1), HOY)]


def test_datos_empleado_no_calcula_la_baja_en_sql():
    """La baja sale de baja_vigente en Python, con el hoy del recalculo: no hay
    un GETDATE() del servidor que pueda derivar del date.today() de Python."""
    db = FakeSession({"FROM Employee e": [{"id": 8}]})
    _datos_empleado(db, 8)
    sql = db.sql_ejecutado()
    assert "GETDATE" not in sql
    assert "EmployeeBaja" not in sql
