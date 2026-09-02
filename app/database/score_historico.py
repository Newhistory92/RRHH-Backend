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

# Nombre de la formula con la que se calculo una corrida. Queda guardado en
# cada fila porque el denominador cambio: un score viejo -promedio de eventos
# por sesion- y uno nuevo -eventos por hora efectiva- no son comparables entre
# si. Sin esto la trayectoria de una persona mostraria un salto que parece
# cambio de desempeno y es cambio de unidad.
FORMULA_ACTUAL = "eventos_por_hora_v1"

# Las corridas anteriores a este cambio quedan marcadas con el nombre viejo.
FORMULA_LEGADA = "eventos_por_sesion_v0"

# Tercera version: la fuente dejo de ser UsuarioAccesoLogs -que registra altas
# y bajas de permisos, no trabajo- y paso a ser LogSistema, filtrado por las
# rutas que un administrador marco como trabajo real. El numerador cambio de
# significado, asi que las corridas anteriores no son comparables con estas.
FORMULA_LOGSISTEMA = "eventos_logsistema_v2"

ALTER_FORMULA_SQL = """
IF COL_LENGTH('ScoreHistorico','formula') IS NULL
ALTER TABLE ScoreHistorico ADD formula NVARCHAR(40) NULL;
"""

# Las filas que ya existen salieron todas de la formula vieja. Se las marca una
# sola vez; el WHERE formula IS NULL hace que repetirlo no toque nada.
MIGRAR_FORMULA_SQL = """
UPDATE ScoreHistorico SET formula = :legada WHERE formula IS NULL;
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla, su indice y la columna de formula. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.execute(text(CREATE_INDEX_SQL))
    db.execute(text(ALTER_FORMULA_SQL))
    db.commit()
    db.execute(text(MIGRAR_FORMULA_SQL), {"legada": FORMULA_LEGADA})
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
                 esExento, ventanaMeses, formula)
            VALUES
                (:employeeId, :score, :metodoVinculo, :idUsuario, :sesiones,
                 :eventos, :esExento, :ventanaMeses, :formula)
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
                "formula": f.get("formula", FORMULA_ACTUAL),
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
                   sesiones, eventos, esExento, ventanaMeses, formula
            FROM ScoreHistorico
            WHERE employeeId = :emp
            ORDER BY calculadoEn DESC
        """),
        {"emp": employee_id, "limite": limite},
    ).mappings().all()
    return [dict(f) for f in filas]
