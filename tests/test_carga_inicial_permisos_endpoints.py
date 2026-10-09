"""
Los tres endpoints de asientos de carga inicial de horas de permiso.

Se invocan las funciones directo con un FakeSession, que es el patron de la
suite: no hay TestClient porque las dependencias de FastAPI (auth y sesion) se
resuelven por inyeccion y aca se pasan a mano.
"""

import pytest
from fastapi import HTTPException

from app.routes import carga_inicial_permisos as m
from tests.fakes import FakeSession


def _db(asientos=None, total=None, cupo=12.0, borrado=True, anio_borrado=2026):
    return FakeSession({
        "SUM(horasConsumidas)": [{"total": total}],
        "ORDER BY cargadoEn DESC": asientos if asientos is not None else [],
        "DELETE FROM ConsumoInicialPermiso": (
            [{"anio": anio_borrado}] if borrado else []
        ),
        "FROM Employee e": [{"cupo": cupo}],
    })


# -- Validacion ----------------------------------------------------------------

@pytest.mark.parametrize("valor", [0, 5, 12.5, 2000])
def test_las_horas_razonables_pasan(valor):
    assert m._validar_horas(valor) == float(valor)


def test_rechaza_horas_negativas():
    with pytest.raises(HTTPException) as e:
        m._validar_horas(-1)
    assert e.value.status_code == 400


def test_el_tope_es_por_asiento_y_no_del_total():
    """
    Un total alto puede ser la suma legitima de varias cargas reales; un solo
    asiento de mas de 2000 horas solo puede ser un error de tipeo.
    """
    with pytest.raises(HTTPException) as e:
        m._validar_horas(2001)
    assert e.value.status_code == 400


def test_rechaza_lo_que_no_es_numero():
    with pytest.raises(HTTPException) as e:
        m._validar_horas("mucho")
    assert e.value.status_code == 400


# -- GET -----------------------------------------------------------------------

def test_el_get_devuelve_null_cuando_no_hay_asientos():
    """null y 0 son estados distintos y el panel los muestra distinto."""
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(total=None))
    assert r["total"] is None
    assert r["asientos"] == []
    assert r["cupoAnual"] == 12.0


def test_el_get_devuelve_cero_cuando_los_asientos_suman_cero():
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(total=0))
    assert r["total"] == 0.0


def test_el_get_lista_los_asientos_con_su_id():
    asientos = [
        {"id": 2, "horasConsumidas": 10.0, "cargadoPor": 3, "cargadoEn": None},
        {"id": 1, "horasConsumidas": 5.0, "cargadoPor": 3, "cargadoEn": None},
    ]
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(asientos=asientos, total=15.0))
    assert r["total"] == 15.0
    assert [a["id"] for a in r["asientos"]] == [2, 1]
    assert r["asientos"][0]["horasConsumidas"] == 10.0


# -- POST ----------------------------------------------------------------------

def test_el_post_agrega_un_asiento_y_recalcula(monkeypatch):
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))

    db = _db()
    r = m.post_carga_inicial_permisos(
        8, {"horasConsumidas": 5}, user={"employeeId": 3}, db=db,
    )

    assert r["ok"] is True
    assert r["horasConsumidas"] == 5.0
    assert recalculos == [(8, r["anio"])]
    assert "INSERT INTO ConsumoInicialPermiso" in db.sql_ejecutado()


def test_el_post_rechaza_un_valor_invalido_antes_de_escribir(monkeypatch):
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: None)
    db = _db()
    with pytest.raises(HTTPException):
        m.post_carga_inicial_permisos(
            8, {"horasConsumidas": -1}, user={"employeeId": 3}, db=db,
        )
    assert "INSERT" not in db.sql_ejecutado()


# -- DELETE --------------------------------------------------------------------

def test_el_delete_borra_el_asiento_y_recalcula(monkeypatch):
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))

    db = _db(borrado=True)
    r = m.delete_carga_inicial_permisos(8, 1, _user={}, db=db)

    assert r["ok"] is True
    assert recalculos == [(8, r["anio"])]
    assert "DELETE FROM ConsumoInicialPermiso" in db.sql_ejecutado()


def test_el_delete_de_un_asiento_ajeno_responde_404(monkeypatch):
    """
    borrar_asiento devuelve False cuando el filtro por employeeId no
    encontro nada: el id de la URL no alcanza para borrar el de otro.
    """
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: None)
    db = _db(borrado=False)
    with pytest.raises(HTTPException) as e:
        m.delete_carga_inicial_permisos(8, 999, _user={}, db=db)
    assert e.value.status_code == 404


def test_el_delete_que_no_borro_nada_no_recalcula(monkeypatch):
    """Sin cambio no hay nada que recalcular."""
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))
    with pytest.raises(HTTPException):
        m.delete_carga_inicial_permisos(8, 999, _user={}, db=_db(borrado=False))
    assert recalculos == []


def test_el_delete_recalcula_el_anio_del_asiento_y_no_el_actual(monkeypatch):
    """
    Un asiento cargado en un anio anterior y borrado despues tiene que
    recalcular SU anio: hoy solo se puede cargar el anio en curso, pero un
    asiento ya cargado sigue siendo de cuando se cargo.
    """
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))

    db = _db(borrado=True, anio_borrado=2024)
    r = m.delete_carga_inicial_permisos(8, 1, _user={}, db=db)

    assert r["anio"] == 2024
    assert recalculos == [(8, 2024)]


# -- El recalculo fallido no tumba la request -----------------------------------

def test_el_post_responde_ok_aunque_el_recalculo_falle(monkeypatch):
    """
    El asiento ya quedo escrito en su propia transaccion antes de intentar
    recalcular: un 500 aca le haria creer a RRHH que la carga no se guardo
    cuando si se guardo. Mismo contrato que create_permission en rrhh.py.
    """
    def recalculo_roto(db, eid, anio):
        raise RuntimeError("la base no responde")

    monkeypatch.setattr(m, "recalcular_anio", recalculo_roto)

    r = m.post_carga_inicial_permisos(
        8, {"horasConsumidas": 5}, user={"employeeId": 3}, db=_db(),
    )

    assert r["ok"] is True
    assert r["horasConsumidas"] == 5.0


def test_el_delete_responde_ok_aunque_el_recalculo_falle(monkeypatch):
    def recalculo_roto(db, eid, anio):
        raise RuntimeError("la base no responde")

    monkeypatch.setattr(m, "recalcular_anio", recalculo_roto)

    r = m.delete_carga_inicial_permisos(8, 1, _user={}, db=_db(borrado=True))

    assert r["ok"] is True
