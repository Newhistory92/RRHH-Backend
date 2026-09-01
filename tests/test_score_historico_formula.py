"""
Versionado de la formula en el historial de score.

El score cambia de denominador -de eventos por sesion a eventos por hora
efectiva-, asi que un numero viejo y uno nuevo no son comparables. Sin dejar
registrado con que formula se calculo cada corrida, la trayectoria de una
persona mostraria un salto que parece un cambio de desempeno y es un cambio
de unidad.
"""

from app.database.score_historico import FORMULA_ACTUAL, CREATE_TABLE_SQL, ALTER_FORMULA_SQL


def test_la_formula_actual_nombra_el_denominador():
    """El nombre tiene que decir que mide, no ser un numero de version."""
    assert "hora" in FORMULA_ACTUAL


def test_el_ddl_de_la_columna_es_idempotente():
    assert "IF COL_LENGTH('ScoreHistorico','formula') IS NULL" in ALTER_FORMULA_SQL


def test_la_tabla_se_crea_solo_si_no_existe():
    assert "IF OBJECT_ID('ScoreHistorico', 'U') IS NULL" in CREATE_TABLE_SQL
