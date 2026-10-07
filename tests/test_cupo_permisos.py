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


# -- recalcular_jornada --------------------------------------------------------

def _db_jornada(ids_empleados):
    """FakeSession para recalcular_jornada: la consulta de ids y el log."""
    return FakeSession({
        "OUTPUT INSERTED.id": [{"id": 99}],
        "WHERE jornadaId": [{"id": eid} for eid in ids_empleados],
    })


def test_recalcular_jornada_solo_toca_los_empleados_de_esa_jornada(monkeypatch):
    """El filtro es lo que evita barrer la nomina entera por un cambio de cupo."""
    from app.services import asistencia_recalc as r

    llamados = []
    monkeypatch.setattr(r, "recalcular_anio",
                        lambda db, eid, anio: llamados.append((eid, anio)) or 1)

    db = _db_jornada([3, 7])
    resultado = r.recalcular_jornada(db, jornada_id=2, anio=2026)

    assert llamados == [(3, 2026), (7, 2026)]
    assert resultado["procesados"] == 2
    assert resultado["filas"] == 2
    assert resultado["errores"] == []
    # El filtro tiene que estar en el SQL, no resolverse en Python.
    assert "jornadaId" in db.sql_ejecutado()


def test_recalcular_jornada_sigue_cuando_un_empleado_falla(monkeypatch):
    """Un legajo roto no puede dejar a los demas con el cupo viejo."""
    from app.services import asistencia_recalc as r

    def fake(db, eid, anio):
        if eid == 3:
            raise RuntimeError("legajo roto")
        return 1

    monkeypatch.setattr(r, "recalcular_anio", fake)

    db = _db_jornada([3, 7])
    resultado = r.recalcular_jornada(db, jornada_id=2, anio=2026)

    assert resultado["procesados"] == 1
    assert len(resultado["errores"]) == 1
    assert resultado["errores"][0]["employeeId"] == 3


# -- Validacion del cupo -------------------------------------------------------

import pytest
from fastapi import HTTPException

from app.routes.schedules import _validar_cupo


def test_el_cupo_no_puede_ser_negativo():
    with pytest.raises(HTTPException) as e:
        _validar_cupo(-1)
    assert e.value.status_code == 400


@pytest.mark.parametrize("valor", [0, 12, 12.5, 2000])
def test_los_cupos_razonables_pasan(valor):
    assert _validar_cupo(valor) == float(valor)


def test_el_cupo_rechaza_el_error_de_tipeo():
    """
    120 en vez de 12 regala diez veces el cupo sin que nadie se entere. El tope
    no es una regla de negocio: es el atajo contra ese error.
    """
    with pytest.raises(HTTPException) as e:
        _validar_cupo(2001)
    assert e.value.status_code == 400


def test_el_cupo_ausente_vale_cero():
    """
    Un POST viejo sin el campo no puede explotar; se interpreta como sin cupo.
    """
    assert _validar_cupo(None) == 0.0


# -- El payload sin el campo no pisa el cupo existente --------------------------

from fastapi.testclient import TestClient


def test_actualizar_sin_el_campo_no_pisa_el_cupo_existente(monkeypatch):
    """
    Un bundle de PWA cacheado de antes de este campo no puede, al guardar una
    jornada, pisarle el cupo real con 0 y disparar un recalculo masivo.
    """
    from app.routes import schedules as s

    recalculos = []
    monkeypatch.setattr(s, "recalcular_jornada",
                        lambda db, jid, anio: recalculos.append((jid, anio)))

    db = FakeSession({
        "SELECT horasPermisoAnual FROM JornadaLaboral": [{"horasPermisoAnual": 12.0}],
    })
    resultado = s.save_jornada.__wrapped__ if hasattr(s.save_jornada, "__wrapped__") else None
    # save_jornada es un endpoint FastAPI con BackgroundTasks inyectado; se
    # invoca la funcion directamente pasando un BackgroundTasks real.
    from fastapi import BackgroundTasks
    bg = BackgroundTasks()
    resp = s.save_jornada(bg, {"id": 2, "nombre": "Full", "horasDia": 8}, db)

    assert resp == {"success": True}
    # No se disparo recalculo: el cupo no cambio.
    assert recalculos == []
    # El UPDATE tiene que haber mandado el cupo previo (12.0), no 0.
    updates = [p for sql, p in db.ejecutadas if "UPDATE JornadaLaboral" in sql]
    assert updates and updates[0]["cupo"] == 12.0


def test_crear_jornada_sin_el_campo_usa_el_default_de_la_columna():
    """Una jornada nueva sin el campo arranca en 12, igual que el DEFAULT de la base."""
    from app.routes import schedules as s
    from fastapi import BackgroundTasks

    db = FakeSession({})
    bg = BackgroundTasks()
    s.save_jornada(bg, {"nombre": "Media Jornada", "horasDia": 4}, db)

    inserts = [p for sql, p in db.ejecutadas if "INSERT INTO JornadaLaboral" in sql]
    assert inserts and inserts[0]["cupo"] == 12.0
