"""
Historial de calculo del score de productividad.

Hasta este cambio el score se recalculaba y se pisaba dentro de get_dashboard:
cada vez que alguien abria Estadisticas se reescribian todos los valores, sin
dejar rastro de que numero tuvo cada persona ni de que lo produjo. Si una
decision de ascenso se cuestionaba, no habia forma de reconstruir la evidencia.

Cada corrida escribe una fila por empleado, incluidos los que quedaron sin
medir: saber que alguien no era medible en una fecha es parte del historial, y
es justamente el dato que evita leer su ausencia como bajo desempeno.

La tabla es de solo agregado. Nada la actualiza ni la borra: es el registro de
lo que el sistema creyo en cada momento.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_TABLE_SQL = """
IF OBJECT_ID('ScoreHistorico', 'U') IS NULL
CREATE TABLE ScoreHistorico (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    employeeId    INT NOT NULL,
    calculadoEn   DATETIME2 NOT NULL DEFAULT (GETDATE()),
    score         DECIMAL(10,2) NULL,
    metodoVinculo NVARCHAR(20) NULL,
    idUsuario     NVARCHAR(100) NULL,
    sesiones      INT NULL,
    eventos       INT NULL,
    esExento      BIT NOT NULL DEFAULT 0,
    ventanaMeses  INT NOT NULL DEFAULT 12
);
"""

# Se consulta siempre por empleado y en orden cronologico inverso ("como venia
# evolucionando esta persona"), asi que ese es el indice que importa.
CREATE_INDEX_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_ScoreHistorico_empleado_fecha')
CREATE INDEX IX_ScoreHistorico_empleado_fecha
    ON ScoreHistorico (employeeId, calculadoEn DESC);
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla y su indice si no existen. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.execute(text(CREATE_INDEX_SQL))
    db.commit()


def registrar_corrida(db: Session, filas: list[dict]) -> None:
    """
    Persiste una corrida completa del calculo.

    Cada fila lleva employeeId y, opcionalmente, score, metodoVinculo,
    idUsuario, sesiones, eventos, esExento y ventanaMeses. Un score en None
    significa "no se lo pudo medir", que no es lo mismo que cero.
    """
    if not filas:
        return

    db.execute(
        text("""
            INSERT INTO ScoreHistorico
                (employeeId, score, metodoVinculo, idUsuario, sesiones, eventos,
                 esExento, ventanaMeses)
            VALUES
                (:employeeId, :score, :metodoVinculo, :idUsuario, :sesiones,
                 :eventos, :esExento, :ventanaMeses)
        """),
        [
            {
                "employeeId": f["employeeId"],
                "score": f.get("score"),
                "metodoVinculo": f.get("metodoVinculo"),
                "idUsuario": f.get("idUsuario"),
                "sesiones": f.get("sesiones"),
                "eventos": f.get("eventos"),
                "esExento": 1 if f.get("esExento") else 0,
                "ventanaMeses": f.get("ventanaMeses", 12),
            }
            for f in filas
        ],
    )
    db.commit()


def historial_empleado(db: Session, employee_id: int, limite: int = 24) -> list[dict]:
    """Ultimas corridas de un empleado, de la mas reciente a la mas vieja."""
    filas = db.execute(
        text("""
            SELECT TOP (:limite)
                   calculadoEn, score, metodoVinculo, idUsuario,
                   sesiones, eventos, esExento, ventanaMeses
            FROM ScoreHistorico
            WHERE employeeId = :emp
            ORDER BY calculadoEn DESC
        """),
        {"emp": employee_id, "limite": limite},
    ).mappings().all()
    return [dict(f) for f in filas]
