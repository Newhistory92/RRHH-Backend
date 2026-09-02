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
