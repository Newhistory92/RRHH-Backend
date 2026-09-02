"""
Tests de la normalizacion de URLs a rutas canonicas.

Los casos salen de datos reales de LogSistema medidos el 2026-09-02.
"""

import pytest

from app.services.normalizar_ruta import normalizar_ruta


@pytest.mark.parametrize("cruda, esperada", [
    # Rutas simples: no cambian
    ("/usuario/login-app", "/usuario/login-app"),
    ("/afiliado/nueva-consulta", "/afiliado/nueva-consulta"),
    ("/", "/"),
    # Query string: se descarta
    ("/orden/buscar?dni=30111222", "/orden/buscar"),
    ("/afiliado?x=1&y=2", "/afiliado"),
    # Segmento numerico: colapsa
    ("/orden/123", "/orden/:id"),
    ("/orden/123/detalle", "/orden/:id/detalle"),
    ("/cron/456", "/cron/:id"),
    # GUID: colapsa
    ("/files/afiliado/f8ee8d1a-b978-4caa-8063-cdbe3032c711",
     "/files/afiliado/:id"),
    # Combinado: ID en el medio y query string
    ("/orden/789/historial?desde=2026-01-01", "/orden/:id/historial"),
    # Varios IDs
    ("/afiliado/12/grupo/34", "/afiliado/:id/grupo/:id"),
])
def test_normaliza(cruda, esperada):
    assert normalizar_ruta(cruda) == esperada


def test_string_vacio_devuelve_barra():
    """Una URL vacia no debe romper el agregado ni generar una ruta ''."""
    assert normalizar_ruta("") == "/"


def test_none_devuelve_barra():
    """LogSistema.url es nullable; None no puede propagar un TypeError."""
    assert normalizar_ruta(None) == "/"


def test_no_colapsa_palabras_con_numeros():
    """'v2' o 'covid19' son nombres de recurso, no identificadores."""
    assert normalizar_ruta("/api/v2/afiliado") == "/api/v2/afiliado"


def test_es_idempotente():
    """Normalizar dos veces debe dar lo mismo: el catalogo se recalcula
    en cada request y una ruta ya normalizada no puede volver a cambiar."""
    una_vez = normalizar_ruta("/orden/123?x=1")
    assert normalizar_ruta(una_vez) == una_vez
