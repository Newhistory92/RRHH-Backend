from fastapi.middleware.cors import CORSMiddleware

def setup_cors(app):
    # Aquí defines qué orígenes pueden acceder al backend
    origins = [
        "http://localhost:3000",   # tu frontend local
        "http://127.0.0.1:3000",   # por compatibilidad
        "http://10.25.2.48:3000",  # Frontend en red local
        # "https://tudominio.com"  # si en un futuro lo desplegás
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,        # dominios permitidos
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$", # permitir cualquier puerto local
        allow_credentials=True,       # permitir cookies/autenticación
        allow_methods=["*"],          # permitir todos los métodos (GET, POST, PUT, DELETE)
        allow_headers=["*"],          # permitir todos los headers
    )
