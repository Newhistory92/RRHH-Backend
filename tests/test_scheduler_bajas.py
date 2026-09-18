"""
El tick diario de bajas.

Solo aplica los EFECTOS colaterales de las bajas que se cumplieron. El corte
de accesos no depende de el: se calcula con la fecha en cada request, asi que
si este job se cae el dado de baja igual queda recortado.
"""

from datetime import date

from app.database.bajas import aplicar_efectos, pendientes_de_aplicar
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def test_no_devuelve_a_quien_ya_figura_de_baja():
    """Solo avanza: el tick nunca reactiva ni retoca a quien ya esta aplicado."""
    db = FakeSession({"FROM EmployeeBaja b": []})
    assert pendientes_de_aplicar(db, HOY) == []


def test_devuelve_a_quien_tiene_la_fecha_cumplida_y_sigue_activo():
    db = FakeSession({"FROM EmployeeBaja b": [{"employeeId": 8}]})
    assert pendientes_de_aplicar(db, HOY) == [8]


def test_aplicar_dos_veces_da_el_mismo_resultado():
    """Idempotente: el segundo pase escribe lo mismo que el primero."""
    db = FakeSession()
    aplicar_efectos(db, 8)
    primera = db.sql_ejecutado()
    db2 = FakeSession()
    aplicar_efectos(db2, 8)
    assert db2.sql_ejecutado() == primera
