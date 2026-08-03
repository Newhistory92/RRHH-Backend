"""
Tablas que el recalculo no puede pisar.

JornadaDiaria es derivada: el recalculo la borra entera y la reinserta. Todo lo
que no se puede reconstruir desde Marcacion -las cargas manuales de RRHH- vive
aca, en JornadaCorreccion, con clave natural (employeeId, fecha) y sin FK al id
de la jornada, que cambia en cada corrida.

JornadaIncidencia si es derivada, pero vive aparte porque es 1:N con el dia.
RecalculoLog es la auditoria de las corridas.
"""

import json
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.marcaciones_norm import Correccion

CREATE_CORRECCION_SQL = """
IF OBJECT_ID('JornadaCorreccion', 'U') IS NULL
CREATE TABLE JornadaCorreccion (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    employeeId   INT           NOT NULL,
    fecha        DATE          NOT NULL,
    entrada      DATETIME2     NULL,
    salida       DATETIME2     NULL,
    corregidoPor INT           NOT NULL,
    corregidoAt  DATETIME2     NOT NULL,
    observacion  NVARCHAR(500) NULL,
    CONSTRAINT UQ_JornadaCorreccion UNIQUE (employeeId, fecha)
);
"""

CREATE_INCIDENCIA_SQL = """
IF OBJECT_ID('JornadaIncidencia', 'U') IS NULL
CREATE TABLE JornadaIncidencia (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    employeeId  INT           NOT NULL,
    fecha       DATE          NOT NULL,
    tipo        NVARCHAR(30)  NOT NULL,
    detalle     NVARCHAR(300) NULL,
    detectadoAt DATETIME2     NOT NULL,
    CONSTRAINT UQ_JornadaIncidencia UNIQUE (employeeId, fecha, tipo)
);
"""

CREATE_INDEX_INCIDENCIA_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_JornadaIncidencia_tipo')
CREATE INDEX IX_JornadaIncidencia_tipo ON JornadaIncidencia (tipo, fecha);
"""

CREATE_RECALCULO_LOG_SQL = """
IF OBJECT_ID('RecalculoLog', 'U') IS NULL
CREATE TABLE RecalculoLog (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    origen       NVARCHAR(20)  NOT NULL,
    disparadoPor INT           NULL,
    employeeId   INT           NULL,
    desde        DATE          NULL,
    hasta        DATE          NULL,
    procesados   INT           NOT NULL DEFAULT 0,
    filas        INT           NOT NULL DEFAULT 0,
    errores      NVARCHAR(MAX) NULL,
    iniciadoAt   DATETIME2     NOT NULL,
    finalizadoAt DATETIME2     NULL
);
"""


def ensure_tables(db: Session) -> None:
    """DDL idempotente. Cada sentencia en su propio batch con su commit."""
    db.execute(text(CREATE_CORRECCION_SQL))
    db.commit()
    db.execute(text(CREATE_INCIDENCIA_SQL))
    db.commit()
    db.execute(text(CREATE_INDEX_INCIDENCIA_SQL))
    db.commit()
    db.execute(text(CREATE_RECALCULO_LOG_SQL))
    db.commit()


# -- Correcciones -------------------------------------------------------------

def correcciones_por_dia(db: Session, employee_id: int, desde: date,
                         hasta: date) -> dict[date, Correccion]:
    """Lo que el recalculo reinyecta al motor para que la carga manual gane."""
    filas = db.execute(text("""
        SELECT fecha, entrada, salida FROM JornadaCorreccion
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    out: dict[date, Correccion] = {}
    for f in filas:
        d = f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
        out[d] = Correccion(entrada=f["entrada"], salida=f["salida"])
    return out


def get_correccion(db: Session, employee_id: int, fecha: date) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT id, employeeId, fecha, entrada, salida, corregidoPor,
               corregidoAt, observacion
        FROM JornadaCorreccion WHERE employeeId = :emp AND fecha = :fecha
    """), {"emp": employee_id, "fecha": fecha}).mappings().first()
    return dict(fila) if fila else None


def upsert_correccion(db: Session, employee_id: int, fecha: date,
                      entrada: Optional[datetime], salida: Optional[datetime],
                      corregido_por: int, observacion: Optional[str]) -> None:
    """
    Inserta o actualiza la correccion del dia. Un extremo en None no borra el
    que ya estaba: RRHH puede cargar la entrada hoy y la salida manana.
    """
    db.execute(text("""
        MERGE JornadaCorreccion AS destino
        USING (SELECT :emp AS employeeId, :fecha AS fecha) AS origen
            ON destino.employeeId = origen.employeeId
           AND destino.fecha = origen.fecha
        WHEN MATCHED THEN UPDATE SET
            entrada      = COALESCE(:entrada, destino.entrada),
            salida       = COALESCE(:salida, destino.salida),
            corregidoPor = :por,
            corregidoAt  = GETDATE(),
            observacion  = :obs
        WHEN NOT MATCHED THEN INSERT
            (employeeId, fecha, entrada, salida, corregidoPor, corregidoAt, observacion)
            VALUES (:emp, :fecha, :entrada, :salida, :por, GETDATE(), :obs);
    """), {"emp": employee_id, "fecha": fecha, "entrada": entrada,
           "salida": salida, "por": corregido_por, "obs": (observacion or None)})
    db.commit()


# -- Incidencias --------------------------------------------------------------

def reemplazar_incidencias(db: Session, employee_id: int, desde: date,
                           hasta: date, filas: list[dict]) -> int:
    """
    Derivadas: se borran y se reinsertan junto con las jornadas del rango. No
    hace commit; lo hace reemplazar_jornadas al cerrar la transaccion del
    recalculo, para que jornadas e incidencias no queden desincronizadas.
    """
    db.execute(text("""
        DELETE FROM JornadaIncidencia
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta})

    ahora = datetime.now()
    for f in filas:
        db.execute(text("""
            INSERT INTO JornadaIncidencia (employeeId, fecha, tipo, detalle, detectadoAt)
            VALUES (:employeeId, :fecha, :tipo, :detalle, :detectadoAt)
        """), {"employeeId": employee_id, "fecha": f["fecha"], "tipo": f["tipo"],
               "detalle": f.get("detalle"), "detectadoAt": ahora})
    return len(filas)


def incidencias_abiertas(db: Session, tipo: Optional[str], desde: date,
                         hasta: date) -> list[dict]:
    filas = db.execute(text("""
        SELECT i.id, i.employeeId, e.name AS employeeName, i.fecha, i.tipo,
               i.detalle, i.detectadoAt
        FROM JornadaIncidencia i
        INNER JOIN Employee e ON e.id = i.employeeId
        WHERE i.fecha >= :desde AND i.fecha <= :hasta
          AND (:tipo IS NULL OR i.tipo = :tipo)
        ORDER BY i.fecha DESC, e.name ASC
    """), {"desde": desde, "hasta": hasta, "tipo": tipo}).mappings().all()
    return [dict(f) for f in filas]


# -- Log de recalculos --------------------------------------------------------

def abrir_recalculo(db: Session, origen: str, disparado_por: Optional[int],
                    employee_id: Optional[int], desde: Optional[date],
                    hasta: Optional[date]) -> int:
    fila = db.execute(text("""
        INSERT INTO RecalculoLog (origen, disparadoPor, employeeId, desde, hasta, iniciadoAt)
        OUTPUT INSERTED.id
        VALUES (:origen, :por, :emp, :desde, :hasta, GETDATE())
    """), {"origen": origen, "por": disparado_por, "emp": employee_id,
           "desde": desde, "hasta": hasta}).mappings().first()
    db.commit()
    return int(fila["id"])


def cerrar_recalculo(db: Session, log_id: int, procesados: int, filas: int,
                     errores: list) -> None:
    db.execute(text("""
        UPDATE RecalculoLog
        SET procesados = :proc, filas = :filas, errores = :err,
            finalizadoAt = GETDATE()
        WHERE id = :id
    """), {"proc": procesados, "filas": filas,
           "err": (json.dumps(errores, ensure_ascii=False) if errores else None),
           "id": log_id})
    db.commit()


def ultimos_recalculos(db: Session, limite: int = 50) -> list[dict]:
    filas = db.execute(text("""
        SELECT TOP (:limite) id, origen, disparadoPor, employeeId, desde, hasta,
               procesados, filas, errores, iniciadoAt, finalizadoAt
        FROM RecalculoLog ORDER BY id DESC
    """), {"limite": int(limite)}).mappings().all()
    return [dict(f) for f in filas]
