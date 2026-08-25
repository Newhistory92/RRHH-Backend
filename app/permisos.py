"""
Catalogo de permisos y su asignacion a roles.

Este modulo es la unica fuente de verdad de que codigos existen y que rol
arranca con cuales. Es data pura: no toca la base ni la red, para que se
pueda testear sin dobles y para que el seed (app/database/permissions.py)
tenga de donde leer.

Los roles se identifican por NOMBRE, no por id: la columna Role.name es
UNIQUE en el esquema, y los ids son un detalle de la instalacion que no
debe filtrarse al codigo.
"""

# Comodin: quien lo tiene pasa cualquier chequeo. Reservado para ADMIN.
COMODIN = "*"

# ---------------------------------------------------------------------------
# Catalogo de codigos
# ---------------------------------------------------------------------------
PERMISOS: frozenset[str] = frozenset({
    "inicio.ver",
    "perfil.editar",
    "asistencia.propia",
    "asistencia.gestionar",
    "licencias.propias",
    "licencias.configurar",
    "documentos.propios",
    "feedback.participar",
    "feedback.configurar",
    "publicaciones.gestionar",
    "reubicacion.solicitar",
    "reubicacion.gestionar",
    "rrhh.gestionar",
    "organigrama.ver",
    "organigrama.gestionar",
    "estadisticas.ver",
    "test.gestionar",
    "ia.usar",
    "activos.configurar",
    "activos.inventario",
    "activos.modelos",
    "admin.gestionar",
})

# Descripciones para la UI de administracion de roles.
DESCRIPCIONES: dict[str, str] = {
    "inicio.ver": "Portal de inicio y feed de publicaciones",
    "perfil.editar": "Editar el CV y perfil propio",
    "asistencia.propia": "Ver la asistencia propia",
    "asistencia.gestionar": "Tablero de asistencia, alertas y relojes",
    "licencias.propias": "Solicitar y ver licencias propias",
    "licencias.configurar": "Configurar tipos de licencia, topes y feriados",
    "documentos.propios": "Documentos del legajo propio",
    "feedback.participar": "Responder encuestas de feedback",
    "feedback.configurar": "Configurar y verificar el modulo de feedback",
    "publicaciones.gestionar": "Crear, editar y borrar publicaciones",
    "reubicacion.solicitar": "Pedir una reubicacion propia",
    "reubicacion.gestionar": "Tablero de reubicacion con analisis de IA",
    "rrhh.gestionar": "Legajos, condicion laboral, horarios y contratos",
    "organigrama.ver": "Ver el organigrama",
    "organigrama.gestionar": "Crear y editar departamentos y oficinas",
    "estadisticas.ver": "Panel estadistico de personal",
    "test.gestionar": "Configuracion de tests",
    "ia.usar": "Chatbot y modulos de inteligencia artificial",
    "activos.configurar": "Categorias, fabricantes, proveedores y estados",
    "activos.inventario": "Alta, baja y edicion de activos",
    "activos.modelos": "Modelos de PC y sus requisitos",
    "admin.gestionar": "Usuarios, roles y configuracion del sistema",
}

# ---------------------------------------------------------------------------
# Base comun: todo empleado, sea cual sea su rol, gestiona lo suyo.
# ---------------------------------------------------------------------------
_BASE = (
    "inicio.ver",
    "perfil.editar",
    "asistencia.propia",
    "licencias.propias",
    "documentos.propios",
    "feedback.participar",
)

# ---------------------------------------------------------------------------
# Asignacion rol -> permisos. Es el estado INICIAL: una vez sembrado, el
# admin lo cambia desde la UI sin tocar este archivo.
# ---------------------------------------------------------------------------
PERMISOS_POR_ROL: dict[str, tuple[str, ...]] = {
    "ADMIN": (COMODIN,),
    "USER": _BASE + (
        "reubicacion.solicitar",
    ),
    "RRHH": _BASE + (
        "asistencia.gestionar",
        "licencias.configurar",
        "feedback.configurar",
        "publicaciones.gestionar",
        "reubicacion.gestionar",
        "rrhh.gestionar",
        "organigrama.ver",
        "organigrama.gestionar",
        "estadisticas.ver",
        "test.gestionar",
        "ia.usar",
    ),
    "ESTADISTA": _BASE + (
        "estadisticas.ver",
    ),
    "TECNICO": _BASE + (
        "activos.configurar",
        "activos.inventario",
        "activos.modelos",
    ),
    "PATRIMONIO": _BASE + (
        "activos.configurar",
        "activos.inventario",
    ),
}


def tiene_permiso(permisos: set[str], requerido: str) -> bool:
    """
    True si el conjunto habilita el codigo pedido.

    El comodin gana siempre; fuera de eso el match es exacto. No hay
    jerarquia ni prefijos: 'activos.inventario' no implica
    'activos.modelos'. Que sea exacto es deliberado — un permiso nuevo
    nunca se cuela por parecido de nombre.
    """
    if COMODIN in permisos:
        return True
    return requerido in permisos
