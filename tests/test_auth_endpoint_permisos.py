"""El endpoint de permisos devuelve la lista ordenada del usuario actual."""

from app.routes.auth import listar_permisos


def test_listar_permisos_devuelve_lista_ordenada():
    user = {"usuario": "emi25", "roleId": 3, "permisos": {"rrhh.gestionar", "inicio.ver"}}
    assert listar_permisos(user) == {"permisos": ["inicio.ver", "rrhh.gestionar"]}


def test_listar_permisos_sin_permisos_devuelve_lista_vacia():
    user = {"usuario": "nadie", "roleId": None, "permisos": set()}
    assert listar_permisos(user) == {"permisos": []}
