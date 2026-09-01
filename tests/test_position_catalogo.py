"""
El cargo del empleado tiene que salir del catalogo, no ser texto libre.

Existe el modulo Configuracion -> "Catalogo de Profesiones y Cargos", que
escribe en la tabla Profession, pero CondicionLaboral.position es una columna
de texto sin relacion con el: hoy guarda lo que sea que llegue. Con texto libre
"Analista" y "analista Sr." son cargos distintos, y cualquier agrupacion por
funcion se rompe en silencio.
"""

from app.routes.rrhh import position_valida

CATALOGO = {"Analista", "Gerente", "Administración Pública"}


def test_acepta_un_cargo_del_catalogo():
    assert position_valida("Analista", CATALOGO) is True


def test_rechaza_un_cargo_que_no_existe():
    assert position_valida("Analista Sr.", CATALOGO) is False


def test_ignora_espacios_al_comparar():
    assert position_valida("  Analista  ", CATALOGO) is True


def test_vacio_es_valido():
    """No cargar el cargo es legitimo; inventarlo no."""
    assert position_valida(None, CATALOGO) is True
    assert position_valida("", CATALOGO) is True


def test_con_catalogo_vacio_no_se_bloquea_la_carga():
    """
    Si nadie cargo el catalogo todavia, exigirlo dejaria el alta de empleados
    inutilizable. Se acepta y queda para normalizar despues.
    """
    assert position_valida("Cualquiera", set()) is True
