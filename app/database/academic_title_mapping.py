"""
Mapeo de títulos académicos a nombres de profesión (texto libre,
mismo valor que TechnicalSkill.profession), administrable desde TestConfig.

Reemplaza el diccionario SPECIAL_TITLE_MAPPINGS que antes vivía
hardcodeado en el frontend (HabilidadesTecnicas.tsx).
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'AcademicTitleMapping' AND xtype = 'U'
)
BEGIN
    CREATE TABLE AcademicTitleMapping (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        tituloAcademico NVARCHAR(255)  NOT NULL,
        profession      NVARCHAR(255)  NOT NULL,
        activo          BIT            NOT NULL DEFAULT 1,
        createdAt       DATETIME2      NOT NULL,
        updatedAt       DATETIME2      NOT NULL
    );
    CREATE INDEX IX_AcademicTitleMapping_titulo ON AcademicTitleMapping (tituloAcademico);
END
"""

SEED_ROWS = [
    ("Bachiller", "Administración Pública"),
    ("Bachillerato", "Administración Pública"),
    ("Administración Pública", "Administración Pública"),
]


def ensure_table(db: Session) -> None:
    """Crea la tabla AcademicTitleMapping si no existe, y siembra los
    3 mapeos que antes estaban hardcodeados en el frontend (solo si la
    tabla está vacía, para no duplicar en cada llamada)."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()

    count = db.execute(text("SELECT COUNT(*) AS c FROM AcademicTitleMapping")).mappings().first()
    if count["c"] == 0:
        now = datetime.utcnow()
        for titulo, profession in SEED_ROWS:
            db.execute(text("""
                INSERT INTO AcademicTitleMapping (tituloAcademico, profession, activo, createdAt, updatedAt)
                VALUES (:titulo, :profession, 1, :createdAt, :updatedAt)
            """), {"titulo": titulo, "profession": profession, "createdAt": now, "updatedAt": now})
        db.commit()


def get_active_mappings(db: Session) -> list[dict]:
    rows = db.execute(text("""
        SELECT id, tituloAcademico, profession
        FROM AcademicTitleMapping
        WHERE activo = 1
    """)).mappings().all()
    return [dict(r) for r in rows]


def save_mapping(db: Session, titulo_academico: str, profession: str, mapping_id: int | None) -> None:
    now = datetime.utcnow()
    if mapping_id:
        db.execute(text("""
            UPDATE AcademicTitleMapping
            SET tituloAcademico = :titulo, profession = :profession, activo = 1, updatedAt = :updatedAt
            WHERE id = :id
        """), {"titulo": titulo_academico, "profession": profession, "updatedAt": now, "id": mapping_id})
    else:
        existing = db.execute(text("""
            SELECT id FROM AcademicTitleMapping WHERE tituloAcademico = :titulo
        """), {"titulo": titulo_academico}).fetchone()
        if existing:
            db.execute(text("""
                UPDATE AcademicTitleMapping
                SET profession = :profession, activo = 1, updatedAt = :updatedAt
                WHERE tituloAcademico = :titulo
            """), {"profession": profession, "updatedAt": now, "titulo": titulo_academico})
        else:
            db.execute(text("""
                INSERT INTO AcademicTitleMapping (tituloAcademico, profession, activo, createdAt, updatedAt)
                VALUES (:titulo, :profession, 1, :createdAt, :updatedAt)
            """), {"titulo": titulo_academico, "profession": profession, "createdAt": now, "updatedAt": now})
    db.commit()


def delete_mapping(db: Session, mapping_id: int) -> bool:
    existing = db.execute(text("SELECT id FROM AcademicTitleMapping WHERE id = :id"), {"id": mapping_id}).fetchone()
    if not existing:
        return False
    db.execute(text("UPDATE AcademicTitleMapping SET activo = 0, updatedAt = :updatedAt WHERE id = :id"),
               {"updatedAt": datetime.utcnow(), "id": mapping_id})
    db.commit()
    return True
