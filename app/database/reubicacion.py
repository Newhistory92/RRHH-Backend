"""
Modulo de Reubicacion Inteligente -- solicitud del empleado (subsistema 1).
Sin campo de oficina/departamento destino: lo determina un subsistema
futuro (motor de matching por IA). Toda solicitud nace en 'Pendiente'.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text


CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'SolicitudReubicacion' AND xtype = 'U'
)
BEGIN
    CREATE TABLE SolicitudReubicacion (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        employeeId          INT            NOT NULL,
        tipo                NVARCHAR(50)   NOT NULL,
        motivo              NVARCHAR(MAX)  NOT NULL,
        estado              NVARCHAR(20)   NOT NULL DEFAULT 'Pendiente',
        officeIdActual      INT            NULL,
        departmentIdActual  INT            NULL,
        createdAt           DATETIME2      NOT NULL,
        updatedAt           DATETIME2      NOT NULL
    );
    CREATE INDEX IX_SolicitudReubicacion_employeeId ON SolicitudReubicacion (employeeId);
END
"""

VALID_TIPOS = {
    "Cambio de oficina",
    "Cambio de departamento",
    "Reubicación por desarrollo profesional",
    "Reubicación por clima laboral",
    "Reubicación por razones personales",
    "Otra",
}


def ensure_table(db: Session) -> None:
    """Crea SolicitudReubicacion si no existe, y agrega la columna
    observacion si la tabla ya existia sin ella (idempotente)."""
    db.execute(text(CREATE_TABLE_SQL))
    db.execute(text("""
        IF COL_LENGTH('SolicitudReubicacion', 'observacion') IS NULL
            ALTER TABLE SolicitudReubicacion ADD observacion NVARCHAR(MAX) NULL;
    """))
    db.commit()
