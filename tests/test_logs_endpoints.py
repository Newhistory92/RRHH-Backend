"""
Tests de los endpoints de /admin/logs.

Los handlers se invocan directamente, sin servidor HTTP, siguiendo el patron
del resto de la suite.
"""

from app.routes.logs_productividad import armar_catalogo


def test_ruta_sin_configuracion_queda_pendiente():
    """Nada entra al score sin decision humana: lo no clasificado es
    'pendiente', no 'no cuenta'."""
    catalogo = armar_catalogo(
        agregado=[{"metodo": "POST", "url": "/afiliado/nueva-consulta",
                   "eventos": 10, "usuarios": 3, "ultimaVez": "2026-09-01"}],
        config={},
    )
    assert catalogo[0]["estado"] == "pendiente"


def test_ruta_con_peso_positivo_cuenta():
    catalogo = armar_catalogo(
        agregado=[{"metodo": "POST", "url": "/afiliado/nueva-consulta",
                   "eventos": 10, "usuarios": 3, "ultimaVez": "2026-09-01"}],
        config={("POST", "/afiliado/nueva-consulta"): 1.0},
    )
    assert catalogo[0]["estado"] == "cuenta"


def test_ruta_con_peso_cero_no_cuenta_y_no_es_pendiente():
    """Peso 0 es una decision tomada: no debe reaparecer como novedad."""
    catalogo = armar_catalogo(
        agregado=[{"metodo": "POST", "url": "/usuario/login",
                   "eventos": 99, "usuarios": 50, "ultimaVez": "2026-09-01"}],
        config={("POST", "/usuario/login"): 0.0},
    )
    assert catalogo[0]["estado"] == "no_cuenta"


def test_urls_con_distinto_id_colapsan_en_una_fila():
    """Sin esto habria 8.514 filas que tildar en vez de 1.830."""
    catalogo = armar_catalogo(
        agregado=[
            {"metodo": "GET", "url": "/orden/123", "eventos": 5,
             "usuarios": 2, "ultimaVez": "2026-09-01"},
            {"metodo": "GET", "url": "/orden/456", "eventos": 7,
             "usuarios": 3, "ultimaVez": "2026-09-02"},
        ],
        config={},
    )
    assert len(catalogo) == 1
    assert catalogo[0]["ruta"] == "/orden/:id"
    assert catalogo[0]["eventos"] == 12


def test_al_colapsar_se_toma_la_ultima_fecha():
    catalogo = armar_catalogo(
        agregado=[
            {"metodo": "GET", "url": "/orden/123", "eventos": 5,
             "usuarios": 2, "ultimaVez": "2026-08-01"},
            {"metodo": "GET", "url": "/orden/456", "eventos": 7,
             "usuarios": 3, "ultimaVez": "2026-09-02"},
        ],
        config={},
    )
    assert catalogo[0]["ultimaVez"] == "2026-09-02"


def test_mismo_path_distinto_metodo_son_filas_distintas():
    """GET /orden y POST /orden no son la misma accion."""
    catalogo = armar_catalogo(
        agregado=[
            {"metodo": "GET", "url": "/orden", "eventos": 5,
             "usuarios": 2, "ultimaVez": "2026-09-01"},
            {"metodo": "POST", "url": "/orden", "eventos": 3,
             "usuarios": 1, "ultimaVez": "2026-09-01"},
        ],
        config={},
    )
    assert len(catalogo) == 2


def test_catalogo_ordenado_por_volumen_descendente():
    """El administrador tilda de arriba hacia abajo: las 25 primeras rutas
    concentran el 79% del volumen."""
    catalogo = armar_catalogo(
        agregado=[
            {"metodo": "GET", "url": "/poco", "eventos": 5,
             "usuarios": 1, "ultimaVez": "2026-09-01"},
            {"metodo": "GET", "url": "/mucho", "eventos": 500,
             "usuarios": 40, "ultimaVez": "2026-09-01"},
        ],
        config={},
    )
    assert [f["ruta"] for f in catalogo] == ["/mucho", "/poco"]


def test_agregado_vacio_devuelve_lista_vacia():
    """Si ObraSocial no responde, la pantalla no puede romperse."""
    assert armar_catalogo(agregado=[], config={}) == []


from app.routes.logs_productividad import (
    ClasificacionRequest,
    RutaClasificada,
    guardar_rutas,
)
from tests.fakes import FakeSession


def test_guardar_persiste_las_filas_recibidas():
    db = FakeSession()
    payload = ClasificacionRequest(rutas=[
        RutaClasificada(metodo="POST", ruta="/afiliado/nueva-consulta",
                        cuenta=True),
        RutaClasificada(metodo="POST", ruta="/usuario/login", cuenta=False),
    ])
    resultado = guardar_rutas(payload=payload, db=db, user={"employeeId": 5})
    assert resultado == {"success": True, "guardadas": 2}


def test_guardar_registra_quien_clasifico():
    """Una decision que cambia scores de ascenso tiene que ser trazable."""
    db = FakeSession()
    payload = ClasificacionRequest(rutas=[
        RutaClasificada(metodo="POST", ruta="/a", cuenta=True),
    ])
    guardar_rutas(payload=payload, db=db, user={"employeeId": 42})
    _sql, params = db.ejecutadas[-1]
    assert params[0]["clasificadoPor"] == 42


def test_guardar_lista_vacia_no_falla():
    db = FakeSession()
    resultado = guardar_rutas(
        payload=ClasificacionRequest(rutas=[]), db=db, user={"employeeId": 1}
    )
    assert resultado == {"success": True, "guardadas": 0}


def test_guardar_nunca_escribe_en_obrasocial():
    """Restriccion dura del proyecto: esa base es de solo lectura."""
    db = FakeSession()
    guardar_rutas(
        payload=ClasificacionRequest(rutas=[
            RutaClasificada(metodo="POST", ruta="/a", cuenta=True),
        ]),
        db=db, user={"employeeId": 1},
    )
    assert "ObraSocial" not in db.sql_ejecutado()


def test_guardar_rutas_no_acepta_employee_id():
    """employee_id ya no es un parametro: no debe poder inyectarse como query param."""
    import inspect
    sig = inspect.signature(guardar_rutas)
    assert "employee_id" not in sig.parameters


from app.routes.logs_productividad import construir_filtros


def test_sin_filtros_solo_excluye_nada():
    where, binds = construir_filtros({})
    assert where == ""
    assert binds == {}


def test_filtro_por_metodo():
    where, binds = construir_filtros({"metodo": "POST"})
    assert "metodo = :metodo" in where
    assert binds["metodo"] == "POST"


def test_filtro_por_texto_en_url_usa_like():
    where, binds = construir_filtros({"texto": "afiliado"})
    assert "url LIKE :texto" in where
    assert binds["texto"] == "%afiliado%"


def test_filtro_por_clase_de_status_exito():
    where, binds = construir_filtros({"clase": "exito"})
    assert "statusCode >= 200" in where and "statusCode < 300" in where


def test_filtro_por_clase_de_status_error_cliente():
    where, _binds = construir_filtros({"clase": "error_cliente"})
    assert "statusCode >= 400" in where and "statusCode < 500" in where


def test_clase_desconocida_se_ignora():
    """Un valor invalido no debe traducirse en un filtro arbitrario."""
    where, _binds = construir_filtros({"clase": "cualquier-cosa"})
    assert "statusCode" not in where


def test_filtros_se_combinan_con_and():
    where, binds = construir_filtros({"metodo": "POST", "texto": "orden"})
    assert where.count("AND") >= 1
    assert binds["metodo"] == "POST" and binds["texto"] == "%orden%"


def test_texto_vacio_no_genera_filtro():
    where, binds = construir_filtros({"texto": ""})
    assert "url LIKE" not in where
    assert "texto" not in binds
