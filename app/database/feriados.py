"""
Feriados de empresa configurables por RRHH -- fechas puntuales que se
excluyen del conteo de dias habiles en Calendario.tsx (frontend), junto
con los feriados publicos argentinos (traidos de una API externa).
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'Feriado' AND xtype = 'U'
)
BEGIN
    CREATE TABLE Feriado (
        id        INT IDENTITY(1,1) PRIMARY KEY,
        fecha     DATE           NOT NULL,
        nombre    NVARCHAR(255)  NOT NULL,
        activo    BIT            NOT NULL DEFAULT 1,
        createdAt DATETIME2      NOT NULL
    );
    CREATE INDEX IX_Feriado_fecha ON Feriado (fecha);
END
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla Feriado si no existe."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def get_feriados(db: Session) -> list[dict]:
    """Lista feriados de empresa activos."""
    rows = db.execute(text("""
        SELECT id, fecha, nombre
        FROM Feriado
        WHERE activo = 1
        ORDER BY fecha ASC
    """)).mappings().all()
    return [dict(r) for r in rows]


def save_feriado(db: Session, fecha: str, nombre: str) -> int:
    """Inserta un nuevo feriado y retorna su id."""
    result = db.execute(text("""
        INSERT INTO Feriado (fecha, nombre, activo, createdAt)
        OUTPUT INSERTED.id
        VALUES (:fecha, :nombre, 1, :createdAt)
    """), {"fecha": fecha, "nombre": nombre, "createdAt": datetime.utcnow()})
    new_id = result.scalar()
    db.commit()
    return new_id


def delete_feriado(db: Session, feriado_id: int) -> bool:
    """Soft delete de un feriado. Retorna False si no existia."""
    existing = db.execute(text("SELECT id FROM Feriado WHERE id = :id"), {"id": feriado_id}).fetchone()
    if not existing:
        return False
    db.execute(text("UPDATE Feriado SET activo = 0 WHERE id = :id"), {"id": feriado_id})
    db.commit()
    return True
