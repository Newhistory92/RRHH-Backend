"""
Módulo de blacklist de tokens JWT persistente en SQL Server.

Crea la tabla TokenBlacklist si no existe y provee funciones para:
  - add_to_blacklist: agregar un token invalidado
  - is_blacklisted: consultar si un token fue invalidado
  - cleanup_expired: limpiar tokens ya expirados (llamar periódicamente)
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Inicialización — tabla creada si no existe al importar el módulo
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'TokenBlacklist' AND xtype = 'U'
)
BEGIN
    CREATE TABLE TokenBlacklist (
        id         INT IDENTITY(1,1) PRIMARY KEY,
        token      NVARCHAR(2048) NOT NULL,
        expires_at DATETIME2      NOT NULL,
        created_at DATETIME2      DEFAULT GETDATE()
    );
    CREATE INDEX IX_TokenBlacklist_token      ON TokenBlacklist (token);
    CREATE INDEX IX_TokenBlacklist_expires_at ON TokenBlacklist (expires_at);
END
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla TokenBlacklist si no existe. Llamar al iniciar la app."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


# ---------------------------------------------------------------------------
# Operaciones principales
# ---------------------------------------------------------------------------

def add_to_blacklist(db: Session, token: str, expires_at: datetime) -> None:
    """
    Registra un token como inválido hasta su fecha de expiración.

    Args:
        db:         Sesión de SQLAlchemy.
        token:      El JWT completo como string.
        expires_at: DateTime de expiración del token (para limpiar luego).
    """
    db.execute(
        text("""
            INSERT INTO TokenBlacklist (token, expires_at)
            VALUES (:token, :expires_at)
        """),
        {"token": token, "expires_at": expires_at}
    )
    db.commit()


def is_blacklisted(db: Session, token: str) -> bool:
    """
    Retorna True si el token fue invalidado explícitamente (logout).

    Solo verifica tokens cuya fecha de expiración aún no pasó
    (los expirados son inválidos por naturaleza, no necesitan blacklist).
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = db.execute(
        text("""
            SELECT 1 FROM TokenBlacklist
            WHERE token = :token
              AND expires_at > :now
        """),
        {"token": token, "now": now}
    ).first()
    return result is not None


def cleanup_expired(db: Session) -> int:
    """
    Elimina tokens con fecha de expiración pasada.
    Retorna la cantidad de filas eliminadas.
    Se recomienda llamar en logout y verify para mantenimiento automático.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = db.execute(
        text("DELETE FROM TokenBlacklist WHERE expires_at <= :now"),
        {"now": now}
    )
    db.commit()
    return result.rowcount
