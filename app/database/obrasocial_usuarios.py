"""
Lecturas sobre la base institucional.

Es de SOLO LECTURA: el sistema RRHH nunca escribe en ObraSocial. Cualquier
INSERT, UPDATE o DELETE contra [ObraSocial].[dbo].* es un bug.

Usuario y Persona se consultan siempre juntos: sin los datos de la persona no
se puede vincular ni crear el empleado, asi que separarlos solo agregaria un
viaje de ida y vuelta.
"""

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

_SELECT_USUARIO = """
    SELECT u.idUsuario, u.nombreUsuario, u.claveUsuario, u.anulado, u.idPersona,
           p.nombrePersona, p.apellidoPersona, p.numeroDocPersona,
           p.sexoPersona, p.telefonoPersona, p.emailPersona,
           p.fechaNacPersona, p.fotoPersona
    FROM [ObraSocial].[dbo].[Usuario] u
    LEFT JOIN [ObraSocial].[dbo].[Persona] p ON p.idPersona = u.idPersona
"""

# Solo empleados de la institucion: excluye afiliados, prestadores, clinicas
# y organismos externos. COALESCE cubre el caso donde la columna es nullable
# y tiene NULL en lugar de 0/False (ambos significan "no es afiliado").
_FILTRO_EMPLEADOS = (
    " COALESCE(u.esAfiliado, 0) = 0"
    " AND u.idPrestador IS NULL"
    " AND u.idClinica IS NULL"
    " AND COALESCE(u.codOrganismoExterno, '') = ''"
    " AND COALESCE(u.codObraSocial, '') = ''"
)


def diagnosticar(db_os: Session, nombre_usuario: str) -> Optional[dict]:
    """
    Por que un usuario concreto no aparece en el tablero.

    Devuelve cada condicion del filtro por separado en lugar de un si/no, que
    es lo unico que permite distinguir "no existe" de "existe pero lo excluye
    tal columna".
    """
    fila = db_os.execute(text("""
        SELECT u.nombreUsuario, u.esAfiliado, u.idPrestador, u.idClinica,
               u.codOrganismoExterno, u.codObraSocial, u.anulado, u.idPersona,
               p.numeroDocPersona,
               CASE WHEN COALESCE(u.esAfiliado, 0) = 0 THEN 1 ELSE 0 END AS pasa_afiliado,
               CASE WHEN u.idPrestador IS NULL THEN 1 ELSE 0 END AS pasa_prestador,
               CASE WHEN u.idClinica IS NULL THEN 1 ELSE 0 END AS pasa_clinica,
               CASE WHEN COALESCE(u.codOrganismoExterno, '') = '' THEN 1 ELSE 0 END AS pasa_organismo,
               CASE WHEN COALESCE(u.codObraSocial, '') = '' THEN 1 ELSE 0 END AS pasa_obrasocial,
               CASE WHEN p.idPersona IS NULL THEN 0 ELSE 1 END AS tiene_persona
        FROM [ObraSocial].[dbo].[Usuario] u
        LEFT JOIN [ObraSocial].[dbo].[Persona] p ON p.idPersona = u.idPersona
        WHERE u.nombreUsuario = :n
    """), {"n": nombre_usuario}).mappings().first()
    return dict(fila) if fila else None


def buscar_por_nombre(db_os: Session, nombre_usuario: str) -> Optional[dict]:
    fila = db_os.execute(
        text(_SELECT_USUARIO + f" WHERE {_FILTRO_EMPLEADOS} AND u.nombreUsuario = :n"),
        {"n": nombre_usuario},
    ).mappings().first()
    return dict(fila) if fila else None


def buscar_por_ids(db_os: Session, id_usuarios: list[str]) -> list[dict]:
    """Los binds se generan: ningun valor entra interpolado en el SQL."""
    if not id_usuarios:
        return []
    binds = {f"id{i}": valor for i, valor in enumerate(id_usuarios)}
    marcadores = ", ".join(f":{clave}" for clave in binds)
    filas = db_os.execute(
        text(_SELECT_USUARIO + f" WHERE {_FILTRO_EMPLEADOS} AND u.idUsuario IN ({marcadores})"),
        binds,
    ).mappings().all()
    return [dict(f) for f in filas]


def listar(db_os: Session) -> list[dict]:
    filas = db_os.execute(
        text(_SELECT_USUARIO + f" WHERE {_FILTRO_EMPLEADOS} ORDER BY p.apellidoPersona, p.nombrePersona")
    ).mappings().all()

    # Deja rastro de cuanto recorta el filtro. Si el tablero sale corto, la
    # diferencia entre los dos numeros dice si sobra filtro o falta dato.
    total = db_os.execute(
        text("SELECT COUNT(*) FROM [ObraSocial].[dbo].[Usuario]")
    ).scalar()
    log.info(
        "Usuarios institucionales: %s de %s pasaron el filtro de empleados",
        len(filas), total,
    )
    return [dict(f) for f in filas]
