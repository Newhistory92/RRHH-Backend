import os

from fastapi.middleware.cors import CORSMiddleware


def setup_cors(app):
    # Aquí defines qué orígenes pueden acceder al backend
    origins = [
        "http://localhost:3000",   # tu frontend local
        "http://127.0.0.1:3000",   # por compatibilidad
        "http://10.25.2.48:3000",  # Frontend en red local
        # "https://tudominio.com"  # si en un futuro lo desplegás
    ]

    # CORS_MODE=open acepta cualquier origen -- solo para el ambiente de
    # pruebas de RRHH, donde el frontend se levanta desde maquinas y puertos
    # distintos que no vale la pena ir agregando a mano una por una. No usar
    # en produccion: con esto cualquier sitio puede llamar al backend
    # llevando las credenciales del usuario logueado.
    modo_abierto = (os.getenv("CORS_MODE") or "").strip().lower() == "open"
    origin_regex = r".*" if modo_abierto else (
        # localhost/127.0.0.1 en cualquier puerto, o cualquier IP de la red
        # institucional (10.x.x.x) en el puerto 3000 -- cubre cualquier PC
        # donde se levante el frontend sin tener que hardcodear cada IP.
        r"^http://(localhost|127\.0\.0\.1)(:\d+)?$|^http://10\.\d+\.\d+\.\d+:3000$"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,        # dominios permitidos
        allow_origin_regex=origin_regex,
        allow_credentials=True,       # permitir cookies/autenticación
        allow_methods=["*"],          # permitir todos los métodos (GET, POST, PUT, DELETE)
        allow_headers=["*"],          # permitir todos los headers
    )
