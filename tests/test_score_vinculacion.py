"""
Vinculacion de identidad entre RRHH y ObraSocial para el score.

El join viejo comparaba User.id con UsuarioAccesoLogs.idUsuario. User.id tiene
formato mixto -enteros como '10' y GUIDs- mientras idUsuario es siempre GUID,
asi que fallaba para casi todos y el empleado terminaba sin score. Ahora el
puente es el DNI, que es un identificador del mundo real.

La funcion de asignacion es pura: recibe los empleados, el mapa de
identidades y los scores medidos, y decide que le toca a cada uno.
"""

from app.routes.stats import asignar_scores


def test_el_empleado_vinculado_recibe_su_score():
    r = asignar_scores([1], {1: "guid-a"}, {"guid-a": 7.5})
    assert r[1] == 7.5


def test_el_empleado_sin_vinculo_queda_sin_dato():
    """Sin identidad resuelta no se lo midio: None, nunca 0.0."""
    r = asignar_scores([1, 2], {1: "guid-a"}, {"guid-a": 7.5})
    assert r[2] is None


def test_el_vinculado_sin_actividad_queda_sin_dato():
    """
    Tiene usuario en ObraSocial pero no genero logs en la ventana. Tampoco se
    lo midio: un 0.0 aca diria que trabajo cero, y lo que pasa es que su
    trabajo no pasa por ese sistema.
    """
    r = asignar_scores([1], {1: "guid-sin-logs"}, {"guid-a": 7.5})
    assert r[1] is None


def test_aparecen_todos_los_empleados():
    """
    Todo empleado tiene que figurar, aunque sea con None. Si se lo omite, el
    UPDATE no lo toca y le queda para siempre el score viejo de una corrida
    anterior.
    """
    r = asignar_scores([1, 2, 3], {}, {})
    assert set(r) == {1, 2, 3}
    assert all(v is None for v in r.values())


def test_sin_empleados_no_devuelve_nada():
    assert asignar_scores([], {1: "guid-a"}, {"guid-a": 7.5}) == {}


# ── Union de las dos vias ─────────────────────────────────────────────────────
#
# Ninguna via sola alcanza. Hay empleados con Persona cargada en ObraSocial y
# sin GUID propio, y otros al reves: sin Persona, pero cuyo User.id de RRHH ES
# el GUID de ObraSocial. Quedarse con una sola pierde gente medible.

from app.routes.stats import combinar_identidades


def test_el_dni_manda_cuando_las_dos_vias_resuelven():
    """
    El DNI es un identificador del mundo real y verificable; el User.id
    coincide por como se creo la cuenta. Ante discrepancia gana el DNI.
    """
    r = combinar_identidades(por_dni={1: "guid-dni"}, por_user_id={1: "guid-user"})
    assert r[1] == "guid-dni"


def test_el_user_id_cubre_a_quien_el_dni_no_resuelve():
    """El caso real del empleado 8: sin Persona cargada, con GUID propio."""
    r = combinar_identidades(por_dni={1: "guid-a"}, por_user_id={8: "guid-b"})
    assert r == {1: "guid-a", 8: "guid-b"}


def test_sin_ninguna_via_no_hay_identidad():
    assert combinar_identidades(por_dni={}, por_user_id={}) == {}


# ── Trazabilidad: con que via se resolvio cada identidad ──────────────────────

from app.routes.stats import metodos_vinculo


def test_el_metodo_registrado_coincide_con_la_identidad_elegida():
    """
    Si combinar_identidades toma el guid del DNI, el metodo tiene que decir
    "dni". Que discrepen haria que el historial mienta sobre su propio origen.
    """
    por_dni = {1: "guid-dni"}
    por_user_id = {1: "guid-user", 8: "guid-b"}
    ident = combinar_identidades(por_dni, por_user_id)
    metodos = metodos_vinculo(por_dni, por_user_id)
    assert metodos[1] == "dni" and ident[1] == "guid-dni"
    assert metodos[8] == "user_id" and ident[8] == "guid-b"


def test_sin_identidad_no_hay_metodo():
    assert metodos_vinculo({}, {}) == {}
