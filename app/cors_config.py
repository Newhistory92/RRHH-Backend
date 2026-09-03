import os

from fastapi.middleware.cors import CORSMiddleware

# Redes privadas (RFC 1918) mas loopback, en http o https y en cualquier
# puerto. Antes el regex exigia 10.x.x.x en el puerto 3000 exacto, asi que
# mover el frontend a otro puerto, a otra subred o a https lo rompia con un
# "Failed to fetch" que no dice CORS por ningun lado y cuesta rastrear.
#
# El limite se mantiene en redes privadas a proposito: con
# allow_credentials=True, abrir esto a cualquier origen dejaria que un sitio
# externo llame al backend con las credenciales del usuario logueado.
_RED_PRIVADA = (
    r"^https?://("
    r"localhost"
    r"|127\.0\.0\.1"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$"
)


def _origenes_extra() -> list[str]:
    """Origenes publicos adicionales, separados por coma.

    Para el dia que el frontend salga a un dominio real: se agrega por
    CORS_EXTRA_ORIGINS sin tocar codigo ni relajar el regex de red privada.
    """
    crudo = os.getenv("CORS_EXTRA_ORIGINS") or ""
    return [o.strip() for o in crudo.split(",") if o.strip()]


def setup_cors(app):
    # CORS_MODE=open acepta cualquier origen -- solo para el ambiente de
    # pruebas de RRHH. No usar en produccion: con esto cualquier sitio puede
    # llamar al backend llevando las credenciales del usuario logueado.
    modo_abierto = (os.getenv("CORS_MODE") or "").strip().lower() == "open"
    origin_regex = r".*" if modo_abierto else _RED_PRIVADA

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origenes_extra(),
        allow_origin_regex=origin_regex,
        allow_credentials=True,       # permitir cookies/autenticación
        allow_methods=["*"],          # permitir todos los métodos (GET, POST, PUT, DELETE)
        allow_headers=["*"],          # permitir todos los headers
    )
