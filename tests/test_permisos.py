"""Tests de la logica pura de permisos: sin base, sin red."""

from app.permisos import (
    COMODIN,
    PERMISOS,
    PERMISOS_POR_ROL,
    tiene_permiso,
)


def test_comodin_habilita_cualquier_permiso():
    assert tiene_permiso({COMODIN}, "rrhh.gestionar") is True
    assert tiene_permiso({COMODIN}, "activos.modelos") is True


def test_permiso_exacto_habilita():
    assert tiene_permiso({"estadisticas.ver"}, "estadisticas.ver") is True


def test_permiso_ausente_no_habilita():
    assert tiene_permiso({"estadisticas.ver"}, "rrhh.gestionar") is False


def test_conjunto_vacio_no_habilita_nada():
    assert tiene_permiso(set(), "inicio.ver") is False


def test_todos_los_roles_del_seed_usan_codigos_del_catalogo():
    for rol, codigos in PERMISOS_POR_ROL.items():
        for codigo in codigos:
            assert codigo in PERMISOS or codigo == COMODIN, (
                f"{rol} referencia el codigo desconocido {codigo!r}"
            )


def test_admin_tiene_comodin():
    assert PERMISOS_POR_ROL["ADMIN"] == (COMODIN,)


def test_base_comun_en_todos_los_roles_no_admin():
    base = {
        "inicio.ver",
        "perfil.editar",
        "asistencia.propia",
        "licencias.propias",
        "documentos.propios",
        "feedback.participar",
    }
    for rol in ("USER", "RRHH", "ESTADISTA", "TECNICO", "PATRIMONIO"):
        assert base.issubset(set(PERMISOS_POR_ROL[rol])), f"{rol} pierde la base comun"


def test_solo_tecnico_gestiona_modelos_de_pc():
    con_modelos = {
        rol for rol, cods in PERMISOS_POR_ROL.items() if "activos.modelos" in cods
    }
    assert con_modelos == {"TECNICO"}


def test_patrimonio_no_gestiona_modelos_pero_si_inventario():
    patrimonio = set(PERMISOS_POR_ROL["PATRIMONIO"])
    assert "activos.modelos" not in patrimonio
    assert "activos.inventario" in patrimonio
    assert "activos.configurar" in patrimonio


def test_estadista_no_ve_organigrama():
    assert "organigrama.ver" not in PERMISOS_POR_ROL["ESTADISTA"]


def test_user_solicita_reubicacion_y_rrhh_la_gestiona():
    assert "reubicacion.solicitar" in PERMISOS_POR_ROL["USER"]
    assert "reubicacion.gestionar" not in PERMISOS_POR_ROL["USER"]
    assert "reubicacion.gestionar" in PERMISOS_POR_ROL["RRHH"]
    assert "reubicacion.solicitar" not in PERMISOS_POR_ROL["RRHH"]
