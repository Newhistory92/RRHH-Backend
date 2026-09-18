"""
El recorte de permisos del dado de baja.

La parte pura -que devuelve exactamente un permiso- se testea sola. La parte
que junta rol y recorte va con FakeSession.
"""

from datetime import date

from app.database.permissions import permisos_efectivos
from app.permisos import COMODIN, recortar_por_baja
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def test_sin_baja_los_permisos_pasan_intactos():
    permisos = {"inicio.ver", "licencias.propias"}
    assert recortar_por_baja(permisos, de_baja=False) == permisos


def test_con_baja_queda_solo_el_legajo():
    permisos = {"inicio.ver", "licencias.propias", "documentos.propios",
                "asistencia.propia", "feedback.participar", "perfil.editar"}
    assert recortar_por_baja(permisos, de_baja=True) == {"documentos.propios"}


def test_el_recorte_tambien_alcanza_al_comodin_de_admin():
    """La baja no depende del rol de quien se fue: el comodin no la esquiva."""
    assert recortar_por_baja({COMODIN}, de_baja=True) == {"documentos.propios"}


def test_el_recorte_deja_el_permiso_aunque_el_rol_no_lo_tuviera():
    """Un rol sin documentos.propios igual conserva su legajo al darse de baja."""
    assert recortar_por_baja({"estadisticas.ver"}, de_baja=True) == {"documentos.propios"}


def _db(permisos_del_rol, bajas):
    return FakeSession({
        "FROM AuthRolePermission": [{"code": c} for c in permisos_del_rol],
        "FROM EmployeeBaja": bajas,
    })


def test_permisos_efectivos_sin_baja_devuelve_los_del_rol():
    db = _db(["inicio.ver", "licencias.propias"], [])
    assert permisos_efectivos(db, 2, 8, HOY) == {"inicio.ver", "licencias.propias"}


def test_permisos_efectivos_con_baja_vigente_recorta():
    db = _db(["inicio.ver", "licencias.propias"],
             [{"fechaBaja": date(2026, 9, 1), "fechaReingreso": None}])
    assert permisos_efectivos(db, 2, 8, HOY) == {"documentos.propios"}


def test_permisos_efectivos_con_baja_futura_no_recorta():
    db = _db(["inicio.ver"],
             [{"fechaBaja": date(2026, 12, 1), "fechaReingreso": None}])
    assert permisos_efectivos(db, 2, 8, HOY) == {"inicio.ver"}


def test_permisos_efectivos_con_baja_reincorporada_no_recorta():
    db = _db(["inicio.ver"],
             [{"fechaBaja": date(2024, 1, 1), "fechaReingreso": date(2025, 1, 1)}])
    assert permisos_efectivos(db, 2, 8, HOY) == {"inicio.ver"}


def test_permisos_efectivos_sin_employee_id_no_consulta_bajas():
    """Una cuenta sin empleado asociado no puede estar de baja."""
    db = _db(["admin.gestionar"], [])
    assert permisos_efectivos(db, 1, None, HOY) == {"admin.gestionar"}
    assert "EmployeeBaja" not in db.sql_ejecutado()
