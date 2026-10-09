"""
Los tres endpoints de extension de tolerancia.

Se invocan las funciones directo con un FakeSession, que es el patron de la
suite: no hay TestClient porque las dependencias de FastAPI (auth y sesion) se
resuelven por inyeccion y aca se pasan a mano.
"""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.routes import extension_tolerancia as m
from tests.fakes import FakeSession

HOY = date.today()
MANIANA = HOY + timedelta(days=1)
AYER = HOY - timedelta(days=1)


def _db(existe=False, borrado=None, extensiones=None):
    return FakeSession({
        "FROM AsistenciaConfig": [{
            "toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
            "fechaInicioModulo": date(2026, 1, 1),
            "toleranciaEstrictaEntradaMin": 7, "toleranciaEstrictaSalidaMin": 5,
            "diasRachaAlerta": 3,
        }],
        "SELECT id FROM ExtensionTolerancia": [{"id": 1}] if existe else [],
        "DELETE FROM ExtensionTolerancia": (
            [{"fecha": borrado}] if borrado is not None else []
        ),
        "ORDER BY fecha DESC": extensiones if extensiones is not None else [],
    })


# -- Validacion ----------------------------------------------------------------

def test_rechaza_una_fecha_pasada():
    """
    Validado en el servidor y no solo con el min del input: el min se saltea
    desde DevTools, y una extension retroactiva reescribiria asistencia ya
    liquidada.
    """
    with pytest.raises(HTTPException) as e:
        m._validar_fecha(AYER.isoformat())
    assert e.value.status_code == 400


def test_acepta_hoy_y_el_futuro():
    assert m._validar_fecha(HOY.isoformat()) == HOY
    assert m._validar_fecha(MANIANA.isoformat()) == MANIANA


def test_rechaza_un_valor_que_no_supera_la_tolerancia_vigente():
    """
    Cargar 5 minutos RECORTARIA el margen de los que viven lejos, al reves
    de lo que el boton promete.
    """
    with pytest.raises(HTTPException) as e:
        m._validar_minutos(5, base=15, extremo="entrada")
    assert e.value.status_code == 400


def test_rechaza_un_valor_igual_a_la_tolerancia_vigente():
    """Igual no es extender: no cambia nada y confunde."""
    with pytest.raises(HTTPException):
        m._validar_minutos(15, base=15, extremo="entrada")


def test_rechaza_el_error_de_tipeo():
    """8 horas ya es una jornada entera y vacia el concepto de tolerancia."""
    with pytest.raises(HTTPException) as e:
        m._validar_minutos(481, base=15, extremo="entrada")
    assert e.value.status_code == 400


def test_acepta_un_valor_razonable():
    assert m._validar_minutos(30, base=15, extremo="entrada") == 30


# -- POST ----------------------------------------------------------------------

def test_el_post_da_de_alta_la_extension(monkeypatch):
    monkeypatch.setattr(m, "_recalcular_si_hace_falta", lambda db, fecha: None)
    db = _db()
    r = m.post_extension(
        {"fecha": MANIANA.isoformat(), "toleranciaEntradaMin": 30},
        user={"employeeId": 3}, db=db,
    )
    assert r["ok"] is True
    assert "INSERT INTO ExtensionTolerancia" in db.sql_ejecutado()


def test_el_post_valida_la_salida_contra_su_propia_base(monkeypatch):
    """
    Que el campo sea opcional no lo exime: una salida de 10 minutos
    recortaria el margen igual que una entrada de 5.
    """
    monkeypatch.setattr(m, "_recalcular_si_hace_falta", lambda db, fecha: None)
    with pytest.raises(HTTPException):
        m.post_extension(
            {"fecha": MANIANA.isoformat(), "toleranciaEntradaMin": 30,
             "toleranciaSalidaMin": 10},
            user={"employeeId": 3}, db=_db(),
        )


def test_el_post_rechaza_una_fecha_que_ya_tiene_extension(monkeypatch):
    monkeypatch.setattr(m, "_recalcular_si_hace_falta", lambda db, fecha: None)
    with pytest.raises(HTTPException) as e:
        m.post_extension(
            {"fecha": MANIANA.isoformat(), "toleranciaEntradaMin": 30},
            user={"employeeId": 3}, db=_db(existe=True),
        )
    assert e.value.status_code == 409


def test_el_post_no_escribe_si_la_validacion_falla(monkeypatch):
    monkeypatch.setattr(m, "_recalcular_si_hace_falta", lambda db, fecha: None)
    db = _db()
    with pytest.raises(HTTPException):
        m.post_extension(
            {"fecha": AYER.isoformat(), "toleranciaEntradaMin": 30},
            user={"employeeId": 3}, db=db,
        )
    assert "INSERT" not in db.sql_ejecutado()


# -- Recalculo -----------------------------------------------------------------

def test_una_extension_futura_no_recalcula(monkeypatch):
    """
    El motor solo computa hasta hoy: el dia de maniana todavia no existe en
    JornadaDiaria, asi que no hay nada que rehacer.
    """
    llamados = []
    monkeypatch.setattr(m, "recalcular_marcados_fuera_del_anillo",
                        lambda db, anio: llamados.append(anio))
    m._recalcular_si_hace_falta(_db(), MANIANA)
    assert llamados == []


def test_una_extension_de_hoy_si_recalcula(monkeypatch):
    llamados = []
    monkeypatch.setattr(m, "recalcular_marcados_fuera_del_anillo",
                        lambda db, anio: llamados.append(anio))
    m._recalcular_si_hace_falta(_db(), HOY)
    assert llamados == [HOY.year]


# -- DELETE --------------------------------------------------------------------

def test_el_delete_borra_y_recalcula_el_anio_de_esa_fecha(monkeypatch):
    """
    Una extension de un anio anterior borrada ahora tiene que recalcular SU
    anio, no el actual.
    """
    llamados = []
    monkeypatch.setattr(m, "recalcular_marcados_fuera_del_anillo",
                        lambda db, anio: llamados.append(anio))
    db = _db(borrado=date(2024, 5, 2))
    r = m.delete_extension(1, _user={}, db=db)
    assert r["ok"] is True
    assert llamados == [2024]


def test_el_delete_de_lo_que_no_existe_responde_404(monkeypatch):
    llamados = []
    monkeypatch.setattr(m, "recalcular_marcados_fuera_del_anillo",
                        lambda db, anio: llamados.append(anio))
    with pytest.raises(HTTPException) as e:
        m.delete_extension(999, _user={}, db=_db(borrado=None))
    assert e.value.status_code == 404
    assert llamados == []
