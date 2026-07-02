"""
Configuracion de periodicidad del ciclo de evaluaciones de Feedback 360.
Fila unica activa, mismo patron que app/database/academic_title_mapping.py.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date


CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'FeedbackConfig' AND xtype = 'U'
)
BEGIN
    CREATE TABLE FeedbackConfig (
        id           INT IDENTITY(1,1) PRIMARY KEY,
        periodicidad NVARCHAR(20)  NOT NULL DEFAULT 'trimestral',
        updatedAt    DATETIME2     NOT NULL
    );
END
"""

VALID_PERIODICIDADES = {"trimestral", "semestral", "anual"}


def ensure_table(db: Session) -> None:
    """Crea FeedbackConfig si no existe y siembra la fila default (trimestral) si esta vacia."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()

    count = db.execute(text("SELECT COUNT(*) AS c FROM FeedbackConfig")).mappings().first()
    if count["c"] == 0:
        db.execute(text("""
            INSERT INTO FeedbackConfig (periodicidad, updatedAt)
            VALUES ('trimestral', :now)
        """), {"now": datetime.utcnow()})
        db.commit()


def get_periodicidad(db: Session) -> str:
    """Devuelve la periodicidad activa ('trimestral' | 'semestral' | 'anual')."""
    row = db.execute(text("SELECT TOP 1 periodicidad FROM FeedbackConfig ORDER BY id ASC")).mappings().first()
    return row["periodicidad"] if row else "trimestral"


def set_periodicidad(db: Session, periodicidad: str) -> None:
    """Actualiza la periodicidad de la unica fila de configuracion."""
    if periodicidad not in VALID_PERIODICIDADES:
        raise ValueError(f"periodicidad debe ser uno de: {VALID_PERIODICIDADES}")
    row = db.execute(text("SELECT TOP 1 id FROM FeedbackConfig ORDER BY id ASC")).mappings().first()
    db.execute(text("""
        UPDATE FeedbackConfig SET periodicidad = :periodicidad, updatedAt = :now
        WHERE id = :id
    """), {"periodicidad": periodicidad, "now": datetime.utcnow(), "id": row["id"]})
    db.commit()


def get_periodo_actual(db: Session) -> date:
    """Calcula el inicio del ciclo activo segun la periodicidad configurada.
    trimestral: primer dia del trimestre en curso (meses 1,4,7,10).
    semestral: primer dia del semestre en curso (meses 1,7).
    anual: 1 de enero del anio en curso.
    """
    periodicidad = get_periodicidad(db)
    today = date.today()

    if periodicidad == "anual":
        return date(today.year, 1, 1)
    if periodicidad == "semestral":
        mes = 1 if today.month < 7 else 7
        return date(today.year, mes, 1)
    mes = ((today.month - 1) // 3) * 3 + 1
    return date(today.year, mes, 1)


def get_periodo_anterior(db: Session) -> date:
    """Calcula el inicio del ciclo inmediatamente anterior al actual,
    restando una unidad de periodicidad (trimestral: -3 meses,
    semestral: -6 meses, anual: -1 anio) a get_periodo_actual.
    """
    periodicidad = get_periodicidad(db)
    actual = get_periodo_actual(db)

    if periodicidad == "anual":
        return date(actual.year - 1, 1, 1)
    if periodicidad == "semestral":
        if actual.month == 1:
            return date(actual.year - 1, 7, 1)
        return date(actual.year, 1, 1)
    mes = actual.month - 3
    anio = actual.year
    if mes <= 0:
        mes += 12
        anio -= 1
    return date(anio, mes, 1)
