"""
Tests de la capa de datos de RutaProductividad.

FakeSession no ejecuta SQL: verifica que se emitan las sentencias correctas
con los binds correctos, y que las funciones traduzcan bien las filas.
"""

from app.database.rutas_productividad import (
    configuracion_actual,
    ensure_table,
    rutas_habilitadas,
    upsert_rutas,
)
from tests.fakes import FakeSession


def test_ensure_table_crea_tabla_en_rrhh_no_en_obrasocial():
    """La configuracion vive en RRHH: ObraSocial es de solo lectura."""
    db = FakeSession()
    ensure_table(db)
    sql = db.sql_ejecutado()
    assert "RutaProductividad" in sql
    assert "ObraSocial" not in sql


def test_ensure_table_es_repetible():
    """Se llama en cada request del catalogo; no puede fallar la segunda vez."""
    db = FakeSession()
    ensure_table(db)
    assert "IF OBJECT_ID" in db.sql_ejecutado()


def test_configuracion_actual_mapea_por_metodo_y_ruta():
    db = FakeSession({"FROM RutaProductividad": [
        {"metodo": "POST", "ruta": "/afiliado/nueva-consulta", "peso": 1.0},
        {"metodo": "POST", "ruta": "/usuario/login", "peso": 0.0},
    ]})
    assert configuracion_actual(db) == {
        ("POST", "/afiliado/nueva-consulta"): 1.0,
        ("POST", "/usuario/login"): 0.0,
    }


def test_rutas_habilitadas_excluye_peso_cero():
    """Peso 0 es 'alguien decidio que no cuenta', y no debe sumar."""
    db = FakeSession({"FROM RutaProductividad": [
        {"metodo": "POST", "ruta": "/afiliado/nueva-consulta", "peso": 1.0},
        {"metodo": "POST", "ruta": "/usuario/login", "peso": 0.0},
    ]})
    assert rutas_habilitadas(db) == {("POST", "/afiliado/nueva-consulta")}


def test_upsert_escribe_peso_1_cuando_cuenta_es_true():
    db = FakeSession()
    upsert_rutas(db, [
        {"metodo": "POST", "ruta": "/afiliado/nueva-consulta", "cuenta": True},
    ], clasificado_por=7)
    _sql, params = db.ejecutadas[-1]
    assert params[0]["peso"] == 1
    assert params[0]["clasificadoPor"] == 7


def test_upsert_escribe_peso_0_cuando_cuenta_es_false():
    db = FakeSession()
    upsert_rutas(db, [
        {"metodo": "POST", "ruta": "/usuario/login", "cuenta": False},
    ], clasificado_por=7)
    _sql, params = db.ejecutadas[-1]
    assert params[0]["peso"] == 0


def test_upsert_devuelve_cantidad_escrita():
    db = FakeSession()
    escritas = upsert_rutas(db, [
        {"metodo": "POST", "ruta": "/a", "cuenta": True},
        {"metodo": "GET", "ruta": "/b", "cuenta": False},
    ], clasificado_por=None)
    assert escritas == 2


def test_upsert_con_lista_vacia_no_ejecuta_nada():
    """Guardar sin cambios no debe abrir una transaccion inutil."""
    db = FakeSession()
    escritas = upsert_rutas(db, [], clasificado_por=1)
    assert escritas == 0
    assert db.ejecutadas == []
    assert db.commits == 0


def test_upsert_usa_merge_para_no_duplicar():
    """La clave (metodo, ruta) es unica: reclasificar actualiza, no inserta."""
    db = FakeSession()
    upsert_rutas(db, [{"metodo": "POST", "ruta": "/a", "cuenta": True}],
                 clasificado_por=1)
    sql = db.sql_ejecutado()
    assert "MERGE" in sql.upper()
