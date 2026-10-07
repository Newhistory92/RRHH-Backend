"""
El cupo anual de permisos sale de la jornada laboral del empleado.

La parte pura (como se consume el cupo) se testea en test_asistencia_calc.
Aca se testea el cableado: que recalcular_anio lea el cupo de la jornada y
que un empleado sin jornada reciba 0.
"""

from datetime import date

from app.services.asistencia_recalc import recalcular_anio
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def _db(cupo):
    """FakeSession con un empleado cuya jornada declara `cupo` horas."""
    return FakeSession({
        "FROM Employee e": [{
            "id": 8, "biometricoId": "123",
            "horaInicio": 8.0, "horaFin": 16.0, "horasTrabajo": 8.0,
            "fechaIngreso": date(2020, 1, 1),
            "horasPermisoAnual": cupo,
        }],
        "FROM AsistenciaConfig": [{
            "toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
            "fechaInicioModulo": date(2026, 1, 1),
            "toleranciaEstrictaEntradaMin": 7, "toleranciaEstrictaSalidaMin": 5,
            "diasRachaAlerta": 3,
        }],
        "FROM EmployeeBaja": [],
    })


def test_el_select_del_empleado_trae_el_cupo_de_la_jornada():
    """Sin el JOIN, recalcular_anio no tendria de donde sacar el cupo."""
    db = _db(12.0)
    recalcular_anio(db, 8, 2026, hoy=HOY)
    sql = db.sql_ejecutado()
    assert "JornadaLaboral" in sql
    assert "horasPermisoAnual" in sql


def test_un_empleado_sin_jornada_no_rompe_el_recalculo():
    """
    jornadaId null hace que el LEFT JOIN devuelva None en el cupo. Tiene que
    resolverse como 0.0 y no explotar en el float().
    """
    db = _db(None)
    # No lanza: es la afirmacion. El cupo 0 en si se testea en el motor.
    recalcular_anio(db, 8, 2026, hoy=HOY)
    assert db.commits >= 1
