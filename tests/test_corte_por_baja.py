"""
La fecha de baja como cota superior de los computos.

Antes esta cota era la fecha de jubilacion y solo aplicaba a ese motivo: a
quien renunciaba le seguian creciendo las vacaciones y el saldo de asistencia
para siempre. Ahora el corte lo pone cualquier baja.
"""

from datetime import date

from app.routes.licenses import _sync_employee_status, calcular_dias_vacaciones
from app.services.asistencia_recalc import rango_de_calculo
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)
INICIO_MODULO = date(2026, 1, 1)


def test_sin_baja_las_vacaciones_cuentan_hasta_hoy():
    sin_corte = calcular_dias_vacaciones("permanente", date(2010, 1, 1), None)
    assert sin_corte > 0


def test_una_renuncia_congela_la_antiguedad_de_vacaciones():
    """El mismo empleado, medido al dia que se fue, no sigue acumulando."""
    al_irse = calcular_dias_vacaciones("permanente", date(2010, 1, 1),
                                       date(2015, 1, 1))
    hasta_hoy = calcular_dias_vacaciones("permanente", date(2010, 1, 1), None)
    assert al_irse < hasta_hoy


def test_la_baja_corta_el_rango_de_asistencia():
    rango = rango_de_calculo(2026, INICIO_MODULO, date(2020, 1, 1),
                             date(2026, 3, 10), HOY)
    assert rango == (INICIO_MODULO, date(2026, 3, 10))


def test_sin_baja_el_rango_llega_hasta_hoy():
    rango = rango_de_calculo(2026, INICIO_MODULO, date(2020, 1, 1), None, HOY)
    assert rango == (INICIO_MODULO, HOY)


def test_una_baja_anterior_al_inicio_del_modulo_no_da_rango():
    assert rango_de_calculo(2026, INICIO_MODULO, date(2020, 1, 1),
                            date(2025, 6, 1), HOY) is None


def test_el_sync_de_status_no_pisa_una_baja():
    """Aprobar una licencia no puede devolver a Activo a quien esta de baja.

    Es el bug que ya tenia el jubilado: _sync_employee_status escribia Activo
    o Licencia sin mirar lo que habia."""
    db = FakeSession({"SELECT status FROM Employee": [{"status": "Baja"}]})
    _sync_employee_status(db, 8)
    assert "UPDATE Employee SET status" not in db.sql_ejecutado()


def test_el_sync_de_status_sigue_funcionando_para_un_activo():
    db = FakeSession({
        "SELECT status FROM Employee": [{"status": "Activo"}],
        "SELECT id FROM License": [],
    })
    _sync_employee_status(db, 8)
    assert "UPDATE Employee SET status" in db.sql_ejecutado()
