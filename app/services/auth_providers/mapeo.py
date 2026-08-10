"""
Traduccion de una fila de ObraSocial.Persona a los campos que necesita
Employee. Son funciones puras: no tocan la base ni saben de sesiones, asi
que se prueban sin ningun doble.

La deteccion de email duplicado NO vive aca porque necesita consultar la
base. El llamador pregunta si el email preferido esta ocupado y, si lo esta,
usa placeholder_email.
"""

DOMINIO_SIN_EMAIL = "sin-email.local"

# ObraSocial guarda el sexo como una letra; RRHH usa la palabra completa, que
# es lo que muestran los selects del frontend.
_GENEROS = {"M": "Masculino", "F": "Femenino"}


def genero(persona: dict) -> str:
    """
    Employee.gender es NOT NULL. Una persona sin sexo cargado se guarda como
    cadena vacia y no como NULL: el frontend ya traduce el vacio a
    "No especificado", y asi el INSERT nunca falla por una columna obligatoria.
    """
    letra = (persona.get("sexoPersona") or "").strip().upper()
    return _GENEROS.get(letra, "")


def nombre_completo(persona: dict) -> str:
    """Nombre y apellido unidos, sin espacios colgando si falta alguno."""
    nombre = (persona.get("nombrePersona") or "").strip()
    apellido = (persona.get("apellidoPersona") or "").strip()
    return " ".join(parte for parte in (nombre, apellido) if parte)


def placeholder_email(nombre_usuario: str) -> str:
    """
    Email de relleno cuando la persona no tiene uno o el suyo ya lo usa otro
    empleado. El dominio es reservado: no resuelve DNS, asi que ningun mail
    sale hacia afuera. Queda visible para que RRHH lo corrija.
    """
    return f"{nombre_usuario}@{DOMINIO_SIN_EMAIL}"


def email_preferido(persona: dict, nombre_usuario: str) -> str:
    email = (persona.get("emailPersona") or "").strip()
    return email or placeholder_email(nombre_usuario)


def persona_a_employee(persona: dict, nombre_usuario: str) -> dict:
    """
    Campos de Employee derivados de Persona.

    El DNI es obligatorio: es la clave que vincula los dos sistemas, y sin el
    no hay forma de encontrar ni de crear el empleado.
    """
    dni = str(persona.get("numeroDocPersona") or "").strip()
    if not dni:
        raise ValueError(
            "La persona no tiene numero de documento cargado en ObraSocial"
        )
    return {
        "dni": dni,
        "name": nombre_completo(persona),
        "email": email_preferido(persona, nombre_usuario),
        "gender": genero(persona),
        "phone": (persona.get("telefonoPersona") or "").strip(),
        "birthDate": persona.get("fechaNacPersona"),
        "photo": persona.get("fotoPersona"),
    }
