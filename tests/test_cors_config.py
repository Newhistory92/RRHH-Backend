"""
CORS: que origenes se aceptan y que los 500 no pierdan los headers.

Los dos casos que cubre este archivo aparecieron juntos en produccion: el
frontend se movio de puerto y todo empezo a fallar con "Failed to fetch", y
cuando ademas hubo un 500 el navegador lo reporto como error de CORS, que
mando la investigacion para el lado equivocado.
"""

import re

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.cors_config import _RED_PRIVADA, setup_cors

ORIGEN = "http://10.25.1.77:3000"


@pytest.mark.parametrize("origen", [
    "http://10.25.1.77:3000",     # el del servidor institucional
    "http://10.25.1.77",          # mismo host en el puerto 80
    "http://10.25.1.77:8080",     # cualquier otro puerto
    "https://10.25.1.77:3000",    # el dia que haya TLS
    "http://192.168.1.50:3000",
    "http://172.20.5.9:3000",
    "http://localhost:3000",
    "http://127.0.0.1:9999",
])
def test_acepta_redes_privadas_en_cualquier_puerto_y_esquema(origen):
    """El regex viejo exigia 10.x.x.x en el puerto 3000 exacto, asi que mover
    el frontend de puerto o ponerlo detras de https lo rompia."""
    assert re.match(_RED_PRIVADA, origen)


@pytest.mark.parametrize("origen", [
    "http://evil.com",
    "https://ejemplo.com.ar",
    "http://172.15.0.1:3000",     # fuera del rango privado 172.16-31
    "http://11.0.0.1:3000",       # fuera de 10.x
])
def test_rechaza_origenes_publicos(origen):
    """Con allow_credentials=True, abrirlo a cualquier origen dejaria que un
    sitio externo llame al backend con las credenciales del usuario."""
    assert not re.match(_RED_PRIVADA, origen)


def _app_de_prueba():
    """Reproduce el orden de middlewares de main.py: el que atrapa errores se
    registra ANTES que CORS, para que CORS quede por fuera y alcance a
    decorar tambien la respuesta de error."""
    app = FastAPI()

    @app.middleware("http")
    async def errores_visibles_para_el_navegador(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"})

    setup_cors(app)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise RuntimeError("explota")

    return app


def test_respuesta_normal_lleva_headers_de_cors():
    cliente = TestClient(_app_de_prueba(), raise_server_exceptions=False)
    r = cliente.get("/ok", headers={"Origin": ORIGEN})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == ORIGEN


def test_error_500_tambien_lleva_headers_de_cors():
    """Sin el middleware, un error no capturado sale por ServerErrorMiddleware
    -que esta por fuera de CORS- y la respuesta viaja sin
    Access-Control-Allow-Origin: el navegador lo muestra como error de CORS y
    esconde el 500 real."""
    cliente = TestClient(_app_de_prueba(), raise_server_exceptions=False)
    r = cliente.get("/boom", headers={"Origin": ORIGEN})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == ORIGEN
