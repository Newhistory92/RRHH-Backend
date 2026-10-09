"""
Persistencia de las extensiones de tolerancia.

Una extension por fecha: es una propiedad del dia, no un libro de asientos.
borrar() devuelve la fecha y no un bool porque el caller necesita saber que
anio recalcular.
"""

from datetime import date

from app.database.extension_tolerancia import (
    agregar, borrar, existe_para_fecha, extensiones_por_fecha, listar,
)
from tests.fakes import FakeSession


def test_listar_devuelve_las_extensiones_con_su_id():
    """El id es lo que el modal necesita para poder borrar una puntual."""
    filas = [{"id": 2, "fecha": date(2026, 10, 15), "toleranciaEntradaMin": 30,
              "toleranciaSalidaMin": None, "cargadoPor": 3, "cargadoEn": None}]
    db = FakeSession({"FROM ExtensionTolerancia": filas})
    r = listar(db)
    assert r[0]["id"] == 2
    assert r[0]["toleranciaEntradaMin"] == 30
    assert r[0]["toleranciaSalidaMin"] is None


def test_extensiones_por_fecha_indexa_por_fecha():
    """Asi el recalculo resuelve cada dia con un lookup y no recorriendo."""
    filas = [{"fecha": date(2026, 10, 15), "toleranciaEntradaMin": 30,
              "toleranciaSalidaMin": 20}]
    db = FakeSession({"FROM ExtensionTolerancia": filas})
    r = extensiones_por_fecha(db, date(2026, 1, 1), date(2026, 12, 31))
    assert r[date(2026, 10, 15)]["toleranciaEntradaMin"] == 30
    assert r[date(2026, 10, 15)]["toleranciaSalidaMin"] == 20


def test_extensiones_por_fecha_acota_al_rango():
    """Sin el filtro, un recalculo de un anio traeria las de todos."""
    db = FakeSession({"FROM ExtensionTolerancia": []})
    extensiones_por_fecha(db, date(2026, 1, 1), date(2026, 12, 31))
    sql, params = db.ejecutadas[0]
    assert "fecha >= :desde" in sql
    assert "fecha <= :hasta" in sql
    assert params == {"desde": date(2026, 1, 1), "hasta": date(2026, 12, 31)}


def test_existe_para_fecha_detecta_la_duplicada():
    db = FakeSession({"FROM ExtensionTolerancia": [{"id": 1}]})
    assert existe_para_fecha(db, date(2026, 10, 15)) is True


def test_existe_para_fecha_sin_fila_es_false():
    db = FakeSession({"FROM ExtensionTolerancia": []})
    assert existe_para_fecha(db, date(2026, 10, 15)) is False


def test_agregar_inserta_con_la_salida_opcional_en_null():
    db = FakeSession({})
    agregar(db, date(2026, 10, 15), 30, None, cargado_por=3)
    sql, params = db.ejecutadas[0]
    assert "INSERT INTO ExtensionTolerancia" in sql
    assert params["salidaMin"] is None
    assert db.commits >= 1


def test_borrar_devuelve_la_fecha_de_lo_borrado():
    """
    El caller necesita el anio de ESA fecha para recalcular, no el actual:
    una extension de diciembre borrada en enero pertenece a diciembre.
    """
    db = FakeSession({"DELETE FROM ExtensionTolerancia": [{"fecha": date(2024, 5, 2)}]})
    assert borrar(db, 1) == date(2024, 5, 2)


def test_borrar_lo_que_no_existe_devuelve_none():
    db = FakeSession({"DELETE FROM ExtensionTolerancia": []})
    assert borrar(db, 999) is None
