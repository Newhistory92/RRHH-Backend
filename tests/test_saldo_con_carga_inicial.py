"""
El excedente de la carga inicial de permisos descuenta del saldo general.

Si alguien ya uso mas horas de las que su cupo cubre, esas horas de mas son
deuda real. No pueden vivir en JornadaDiaria -el recalculo la borra y regenera
entera, y no habria dia al que atribuirlas sin inventarlo-, asi que se
descuentan al calcular el saldo.

Lo que mas importa acá es que haya UNA sola definicion del saldo: los tableros
leen Employee.horas, que es donde _sincronizar_horas deja el resultado de
saldo_acumulado. Si alguno volviera a sumar saldoDia por su cuenta, se
saltearia este descuento sin que nadie lo note.
"""

from app.database.asistencia import (
    excedente_carga_inicial, saldo_acumulado, tablero,
)
from tests.fakes import FakeSession


def _db(saldo_dias=0.0, excedente=0.0):
    return FakeSession({
        "SUM(saldoDia)": [{"s": saldo_dias}],
        "AS excedente": [{"excedente": excedente}],
    })


def test_sin_carga_inicial_el_saldo_es_la_suma_de_los_dias():
    assert saldo_acumulado(_db(saldo_dias=-4.0), 8) == -4.0


def test_el_excedente_descuenta_del_saldo():
    """10 a favor por los dias, 13 de excedente: queda debiendo 3."""
    assert saldo_acumulado(_db(saldo_dias=10.0, excedente=13.0), 8) == -3.0


def test_el_excedente_profundiza_un_saldo_ya_negativo():
    assert saldo_acumulado(_db(saldo_dias=-2.0, excedente=13.0), 8) == -15.0


def test_el_excedente_se_mide_contra_el_cupo_de_la_jornada():
    """
    Sin el JOIN a JornadaLaboral no habria cupo contra el que comparar, y
    todas las horas cargadas contarian como excedente.
    """
    db = _db(excedente=0.0)
    excedente_carga_inicial(db, 8)
    sql = db.sql_ejecutado()
    assert "JornadaLaboral" in sql
    assert "horasPermisoAnual" in sql


def test_un_empleado_sin_jornada_cuenta_todo_como_excedente():
    """
    Sin jornada el cupo es 0, asi que cada hora cargada es excedente. El
    COALESCE del SQL es lo que evita que el NULL del LEFT JOIN anule la resta.
    """
    db = _db(excedente=0.0)
    excedente_carga_inicial(db, 8)
    assert "COALESCE(j.horasPermisoAnual, 0)" in db.sql_ejecutado()


def test_el_excedente_se_mide_sobre_el_total_y_no_por_asiento():
    """
    Con asientos, comparar cada fila contra el cupo da mal: dos asientos de
    10 contra un cupo de 12 son 20 en total y 8 de excedente, pero ninguna
    fila sola supera 12. El SUM tiene que estar adentro de la resta.
    """
    db = _db(excedente=0.0)
    excedente_carga_inicial(db, 8)
    sql = db.sql_ejecutado()
    # La resta opera sobre la suma de los asientos, no sobre cada fila.
    assert "SUM(ci.horasConsumidas)" in sql
    # Y ya no hay un CASE por fila comparando cada asiento contra el cupo.
    assert "CASE WHEN ci.horasConsumidas >" not in sql


# -- Una sola definicion del saldo ---------------------------------------------

def test_el_tablero_lee_el_saldo_sincronizado_y_no_vuelve_a_sumar_los_dias():
    """
    El tablero mostraba SUM(saldoDia) por su cuenta. Con el excedente eso se
    saltearia el descuento, asi que ahora lee Employee.horas, que es donde
    _sincronizar_horas deja el saldo ya resuelto.
    """
    db = FakeSession({"FROM Employee e": []})
    tablero(db, desde=None, hasta=None)
    sql = db.sql_ejecutado()
    assert "e.horas" in sql
    # La suma por empleado que se saltaba el descuento ya no esta.
    assert "SUM(saldoDia) AS saldo" not in sql
