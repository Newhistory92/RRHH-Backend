"""
El consumo inicial achica el banco con el que arranca el anio.

El test que mas importa es el ultimo: descuenta aunque el dia no tenga
marcaciones. Es lo que distingue este camino del de backdatear un permiso, que
no serviria -calcular_dia ignora a proposito los permisos de dias sin fichadas.
"""

from datetime import date

from app.services import asistencia_recalc as r
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def _db(cupo, carga_inicial):
    """
    FakeSession con un empleado, su cupo de jornada y su carga inicial.

    carga_inicial None simula que no hay fila en ConsumoInicialPermiso.
    """
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
        # "SUM(horasConsumidas)" y no "FROM ConsumoInicialPermiso": esa tabla
        # la leen DOS consultas distintas (el total de total_de_empleado y el
        # excedente que descuenta saldo_acumulado), y FakeSession matchea por
        # el primer fragmento que encuentra. Con el nombre de la tabla a
        # secas, la fila de una le llegaba a la otra.
        "AS excedente": [{"excedente": 0.0}],
        "SUM(horasConsumidas)": [{"total": carga_inicial}],
    })


def _banco_usado(monkeypatch, db):
    """Corre recalcular_anio y devuelve el banco que recibio el motor."""
    capturado = {}

    def fake_calcular_anio(dias, tolerancias, banco_anual):
        capturado["banco"] = banco_anual
        return []

    monkeypatch.setattr(r, "calcular_anio", fake_calcular_anio)
    r.recalcular_anio(db, 8, 2026, hoy=HOY)
    return capturado["banco"]


def test_sin_carga_inicial_el_banco_es_el_cupo_entero(monkeypatch):
    assert _banco_usado(monkeypatch, _db(cupo=12.0, carga_inicial=None)) == 12.0


def test_la_carga_inicial_achica_el_banco(monkeypatch):
    assert _banco_usado(monkeypatch, _db(cupo=12.0, carga_inicial=5.0)) == 7.0


def test_una_carga_mayor_al_cupo_deja_el_banco_en_cero(monkeypatch):
    """
    Esa persona ya se paso: el banco arranca vacio y todo permiso del anio va
    derecho a horas a recuperar. Nunca negativo.
    """
    assert _banco_usado(monkeypatch, _db(cupo=12.0, carga_inicial=20.0)) == 0.0


def test_una_carga_en_cero_deja_el_cupo_entero(monkeypatch):
    """Cero es una afirmacion ("no uso ninguna"), no una ausencia de dato."""
    assert _banco_usado(monkeypatch, _db(cupo=12.0, carga_inicial=0.0)) == 12.0


def test_descuenta_aunque_el_empleado_no_tenga_jornada(monkeypatch):
    """Sin jornada el cupo es 0, y el banco no puede irse a negativo."""
    assert _banco_usado(monkeypatch, _db(cupo=None, carga_inicial=5.0)) == 0.0


def test_el_descuento_no_depende_de_las_marcaciones(monkeypatch):
    """
    El motivo de ser de toda la feature.

    El FakeSession no devuelve ninguna marcacion, asi que todos los dias del
    anio quedan sin fichadas. Aun asi el banco llega achicado al motor: el
    descuento ocurre ANTES de calcular ningun dia. Un permiso backdateado a un
    dia sin marcaciones no lograria esto, porque calcular_dia los ignora.
    """
    db = _db(cupo=12.0, carga_inicial=5.0)
    assert _banco_usado(monkeypatch, db) == 7.0
    # Se confirma que efectivamente no habia marcaciones que ayudaran.
    assert "FROM Marcacion" in db.sql_ejecutado()
