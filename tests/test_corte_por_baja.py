"""
La fecha de baja como cota superior de los computos.

Antes esta cota era la fecha de jubilacion y solo aplicaba a ese motivo: a
quien renunciaba le seguian creciendo las vacaciones y el saldo de asistencia
para siempre. Ahora el corte lo pone cualquier baja.
"""

from datetime import date

from app.routes.licenses import (
    _sync_employee_status,
    calcular_dias_vacaciones,
    tipos_disponibles_de,
)
from app.services.asistencia_recalc import _datos_empleado, rango_de_calculo
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)
INICIO_MODULO = date(2026, 1, 1)


def _respuestas_tipos_disponibles(baja_rows: list[dict]) -> dict:
    """
    Fragmentos que necesita tipos_disponibles_de, en el orden en que
    FakeSession los evalua. Los mas especificos van primero para que
    ninguno le gane por error a otro (ver FakeSession en tests/fakes.py).
    """
    return {
        "FROM EmployeeBaja": baja_rows,
        "FROM ConfiguracionLicencias c": [
            {"nombre": "Vacaciones", "diasTotales": 0, "consumidos": 0},
        ],
        "FROM SaldoInicialLicencia": [],
        "FROM Employee e": [{
            "tipoContrato": "permanente",
            "fechaIngreso": date(2005, 1, 1),
            "gender": "Masculino",
            "roleName": "Empleado",
        }],
    }


def test_la_baja_vigente_reduce_los_dias_de_vacaciones_del_catalogo():
    """
    Prueba de punta a punta (con FakeSession) de que una fila de EmployeeBaja
    llega de verdad hasta el total de vacaciones que ofrece el catalogo.

    Sin baja, la antiguedad se cuenta hasta hoy (2005 -> hoy son 20+ anios,
    30 dias). Con una baja vigente en 2008 (3 anios de antiguedad), el corte
    congela el calculo ahi y da bastante menos. Si el call site volviera a
    pasar None en vez de fecha_de_corte(...), las dos corridas darian el
    mismo numero (30) y este test fallaria.
    """
    db_sin_baja = FakeSession(_respuestas_tipos_disponibles([]))
    catalogo_sin_baja = tipos_disponibles_de(db_sin_baja, 8, fecha_referencia=HOY)
    vac_sin_baja = next(
        t for t in catalogo_sin_baja["tipos"] if t["nombre"] == "Vacaciones"
    )

    db_con_baja = FakeSession(_respuestas_tipos_disponibles([
        {"fechaBaja": date(2008, 1, 1), "fechaReingreso": None},
    ]))
    catalogo_con_baja = tipos_disponibles_de(db_con_baja, 8, fecha_referencia=HOY)
    vac_con_baja = next(
        t for t in catalogo_con_baja["tipos"] if t["nombre"] == "Vacaciones"
    )

    assert vac_sin_baja["diasTotales"] == 30
    assert vac_con_baja["diasTotales"] == 10
    assert vac_con_baja["diasTotales"] < vac_sin_baja["diasTotales"]


def test_datos_empleado_de_asistencia_usa_la_misma_nocion_de_baja_vigente():
    """
    _datos_empleado trae fechaBaja con un subquery propio en SQL (no pasa por
    baja_vigente en Python), asi que tiene que codificar a mano el mismo
    criterio: ignorar reingresados y bajas todavia no cumplidas. Se verifica
    inspeccionando el SQL ejecutado, sin asumir formato mas alla de esos dos
    filtros.
    """
    db = FakeSession({
        "FROM Employee e": [{
            "id": 8, "biometricoId": "123",
            "horaInicio": None, "horaFin": None, "horasTrabajo": None,
            "fechaIngreso": date(2005, 1, 1), "fechaBaja": None,
        }],
    })
    _datos_empleado(db, 8)
    sql = db.sql_ejecutado()
    assert "fechaReingreso IS NULL" in sql
    assert "fechaBaja <= CAST(GETDATE() AS DATE)" in sql


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
