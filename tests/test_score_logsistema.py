"""
Tests de la migracion del score a LogSistema.

La fuente anterior, UsuarioAccesoLogs, registra altas y bajas de permisos: no
mide trabajo. Estos tests fijan que solo entre al score lo que un humano
habilito, atribuible y exitoso.
"""

from app.database.score_historico import FORMULA_ACTUAL, FORMULA_LOGSISTEMA, FORMULA_VIGENTE
from app.routes.stats import agrupar_por_usuario


HABILITADAS = {("POST", "/afiliado/nueva-consulta")}


def test_suma_solo_las_rutas_habilitadas():
    filas = [
        {"idUsuario": "u1", "metodo": "POST",
         "url": "/afiliado/nueva-consulta", "eventos": 10},
        {"idUsuario": "u1", "metodo": "POST",
         "url": "/usuario/login", "eventos": 99},
    ]
    assert agrupar_por_usuario(filas, HABILITADAS)["u1"]["eventos"] == 10


def test_ruta_no_habilitada_no_crea_usuario():
    """Quien solo tiene actividad no habilitada queda sin medir, que no es
    lo mismo que medido en cero."""
    filas = [{"idUsuario": "u2", "metodo": "POST",
              "url": "/usuario/login", "eventos": 99}]
    assert agrupar_por_usuario(filas, HABILITADAS) == {}


def test_normaliza_antes_de_comparar():
    """La ruta habilitada esta guardada normalizada; la fila viene cruda."""
    filas = [{"idUsuario": "u1", "metodo": "GET",
              "url": "/orden/123", "eventos": 4}]
    resultado = agrupar_por_usuario(filas, {("GET", "/orden/:id")})
    assert resultado["u1"]["eventos"] == 4


def test_suma_varias_rutas_del_mismo_usuario():
    filas = [
        {"idUsuario": "u1", "metodo": "POST",
         "url": "/afiliado/nueva-consulta", "eventos": 10},
        {"idUsuario": "u1", "metodo": "GET",
         "url": "/orden/1", "eventos": 5},
    ]
    habilitadas = HABILITADAS | {("GET", "/orden/:id")}
    assert agrupar_por_usuario(filas, habilitadas)["u1"]["eventos"] == 15


def test_idusuario_se_normaliza_a_minuscula():
    """La vinculacion por DNI produce GUIDs en minuscula; si no coinciden,
    el empleado queda sin score sin que nada lo avise."""
    filas = [{"idUsuario": "U1-ABC", "metodo": "POST",
              "url": "/afiliado/nueva-consulta", "eventos": 3}]
    assert "u1-abc" in agrupar_por_usuario(filas, HABILITADAS)


def test_sin_rutas_habilitadas_no_mide_a_nadie():
    """Antes de que alguien clasifique, nadie tiene score medido: el sistema
    no inventa numeros a partir de una configuracion vacia."""
    filas = [{"idUsuario": "u1", "metodo": "POST",
              "url": "/afiliado/nueva-consulta", "eventos": 10}]
    assert agrupar_por_usuario(filas, set()) == {}


def test_la_formula_nueva_es_distinta_de_la_anterior():
    """Sin esto, el historial viejo y el nuevo se mezclarian en el mismo
    grafico de trayectoria y un cambio de unidad se leeria como caida."""
    assert FORMULA_LOGSISTEMA == "eventos_logsistema_v2"
    assert FORMULA_LOGSISTEMA != FORMULA_ACTUAL


def test_formula_vigente_coincide_con_formula_de_escritura():
    """El escritor y los lectores deben usar el mismo identificador."""
    assert FORMULA_VIGENTE == FORMULA_LOGSISTEMA, (
        "FORMULA_VIGENTE debe apuntar a FORMULA_LOGSISTEMA para que lo que "
        "se escribe en ScoreHistorico sea lo que los lectores consultan."
    )


def test_sync_retorna_sin_calcular_cuando_no_hay_rutas_habilitadas():
    """Con rutas vacias, sync no debe actualizar scores: evita anular los existentes."""
    from unittest.mock import MagicMock, patch

    db = MagicMock()
    stats_db = MagicMock()

    with patch("app.routes.stats.rutas_habilitadas", return_value=set()), \
         patch("app.routes.stats.ensure_historico"), \
         patch("app.routes.stats.calculate_productivity_scores") as mock_calc:
        from app.routes.stats import sync_productivity_scores
        sync_productivity_scores(db, stats_db)
        mock_calc.assert_not_called()
