"""
Portal de Comunicacion Institucional -- nucleo de publicaciones (subsistema 1).
Modelo de datos: Publication (tabla principal) + PublicationTarget (destinos,
1:N). Estado efectivo (Programada/Publicada/Archivada) se calcula por fecha;
solo se persiste esBorrador. Creacion idempotente via ensure_table.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text


CATEGORIA_AVISO_IMPORTANTE = "Aviso Importante"
CATEGORIA_MANTENIMIENTO = "Mantenimiento y Reparaciones"

VALID_CATEGORIAS = {
    "Noticia Institucional",
    "Circular",
    "Resolución",
    CATEGORIA_MANTENIMIENTO,
    CATEGORIA_AVISO_IMPORTANTE,
    "Evento Institucional",
    "Oportunidad Interna",
    "Beneficio para Empleados",
    "Comunicación de RRHH",
}

VALID_PRIORIDADES = {"Baja", "Normal", "Alta", "Urgente"}

VALID_ESTADOS_MANTENIMIENTO = {
    "Programado",
    "En curso",
    "Completado",
    "Suspendido",
    "Reprogramado",
}

VALID_SCOPES = {"institucion", "departamento", "oficina"}


CREATE_PUBLICATION_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects WHERE name = 'Publication' AND xtype = 'U'
)
BEGIN
    CREATE TABLE Publication (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        titulo              NVARCHAR(300)  NOT NULL,
        resumen             NVARCHAR(MAX)  NULL,
        contenido           NVARCHAR(MAX)  NULL,
        categoria           NVARCHAR(50)   NOT NULL,
        prioridad           NVARCHAR(20)   NOT NULL DEFAULT 'Normal',
        estadoMantenimiento NVARCHAR(20)   NULL,
        esBorrador          BIT            NOT NULL DEFAULT 1,
        destacada           BIT            NOT NULL DEFAULT 0,
        fijada              BIT            NOT NULL DEFAULT 0,
        fechaPublicacion    DATETIME2      NULL,
        fechaExpiracion     DATETIME2      NULL,
        autorEmployeeId     INT            NULL,
        activo              BIT            NOT NULL DEFAULT 1,
        createdAt           DATETIME2      NOT NULL,
        updatedAt           DATETIME2      NOT NULL
    );
END
"""

CREATE_TARGET_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects WHERE name = 'PublicationTarget' AND xtype = 'U'
)
BEGIN
    CREATE TABLE PublicationTarget (
        id            INT IDENTITY(1,1) PRIMARY KEY,
        publicationId INT           NOT NULL,
        scope         NVARCHAR(20)  NOT NULL,
        departmentId  INT           NULL,
        officeId      INT           NULL
    );
    CREATE INDEX IX_PublicationTarget_publicationId ON PublicationTarget (publicationId);
END
"""


def ensure_table(db: Session) -> None:
    """Crea Publication y PublicationTarget si no existen (idempotente)."""
    db.execute(text(CREATE_PUBLICATION_SQL))
    db.execute(text(CREATE_TARGET_SQL))
    db.commit()
