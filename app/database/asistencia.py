"""
Persistencia del modulo de asistencia: JornadaDiaria (una fila por empleado por
dia) y AsistenciaConfig (fila unica con las tolerancias).

JornadaDiaria es derivada: se puede borrar entera y regenerarla desde Marcacion
mas los datos de horario, licencias y permisos. Por eso el recalculo reemplaza
el rango en lugar de intentar actualizar fila por fila.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_JORNADA_SQL = """
IF OBJECT_ID('JornadaDiaria', 'U') IS NULL
CREATE TABLE JornadaDiaria (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    employeeId      INT           NOT NULL,
    fecha           DATE          NOT NULL,
    estado          NVARCHAR(20)  NOT NULL,
    horasRequeridas DECIMAL(5,2)  NOT NULL,
    horasTrabajadas DECIMAL(5,2)  NOT NULL,
    saldoDia        DECIMAL(5,2)  NOT NULL,
    entrada         DATETIME2     NULL,
    salida          DATETIME2     NULL,
    entradaManual   BIT           NOT NULL DEFAULT 0,
    salidaManual    BIT           NOT NULL DEFAULT 0,
    permisoBanco    DECIMAL(5,2)  NOT NULL DEFAULT 0,
    permisoDeuda    DECIMAL(5,2)  NOT NULL DEFAULT 0,
    permisoOficial  DECIMAL(5,2)  NOT NULL DEFAULT 0,
    corregidoPor    INT           NULL,
    corregidoAt     DATETIME2     NULL,
    observacion     NVARCHAR(500) NULL,
    calculadoAt     DATETIME2     NOT NULL,
    CONSTRAINT UQ_JornadaDiaria UNIQUE (employeeId, fecha)
);
"""

CREATE_INDEX_ESTADO_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_JornadaDiaria_estado')
CREATE INDEX IX_JornadaDiaria_estado ON JornadaDiaria (estado, fecha);
"""

CREATE_CONFIG_SQL = """
IF OBJECT_ID('AsistenciaConfig', 'U') IS NULL
CREATE TABLE AsistenciaConfig (
    id                   INT       PRIMARY KEY,
    toleranciaEntradaMin INT       NOT NULL DEFAULT 15,
    toleranciaSalidaMin  INT       NOT NULL DEFAULT 15,
    fechaInicioModulo    DATE      NOT NULL,
    updatedAt            DATETIME2 NOT NULL
);
"""

ALTER_PERMISSION_OFICIAL_SQL = """
IF COL_LENGTH('Permission','oficial') IS NULL
ALTER TABLE Permission ADD oficial BIT NOT NULL DEFAULT 0;
"""

# La fecha de arranque por defecto es la marcacion mas antigua registrada: antes
# de esa fecha no existe informacion de reloj y calcular ausencias seria inventar.
SEED_CONFIG_SQL = """
IF NOT EXISTS (SELECT 1 FROM AsistenciaConfig WHERE id = 1)
INSERT INTO AsistenciaConfig (id, toleranciaEntradaMin, toleranciaSalidaMin,
                              fechaInicioModulo, updatedAt)
VALUES (1, 15, 15,
        COALESCE((SELECT CAST(MIN(fechaHora) AS DATE) FROM Marcacion), CAST(GETDATE() AS DATE)),
        GETDATE());
"""


def ensure_tables(db: Session) -> None:
    """DDL idempotente. Cada sentencia en su propio batch con su commit."""
    db.execute(text(CREATE_JORNADA_SQL))
    db.commit()
    db.execute(text(CREATE_INDEX_ESTADO_SQL))
    db.commit()
    db.execute(text(CREATE_CONFIG_SQL))
    db.commit()
    db.execute(text(ALTER_PERMISSION_OFICIAL_SQL))
    db.commit()
    db.execute(text(SEED_CONFIG_SQL))
    db.commit()


def get_config(db: Session) -> dict:
    fila = db.execute(text("""
        SELECT toleranciaEntradaMin, toleranciaSalidaMin, fechaInicioModulo
        FROM AsistenciaConfig WHERE id = 1
    """)).mappings().first()
    if fila is None:
        return {"toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
                "fechaInicioModulo": date.today()}
    return dict(fila)


def update_config(db: Session, tol_entrada: int, tol_salida: int) -> dict:
    db.execute(text("""
        UPDATE AsistenciaConfig
        SET toleranciaEntradaMin = :te, toleranciaSalidaMin = :ts, updatedAt = GETDATE()
        WHERE id = 1
    """), {"te": int(tol_entrada), "ts": int(tol_salida)})
    db.commit()
    return get_config(db)


def reemplazar_jornadas(db: Session, employee_id: int, desde: date, hasta: date,
                        filas: list[dict]) -> int:
    """
    Borra el rango del empleado y reinserta. JornadaDiaria es derivada, asi que
    reemplazar es mas simple y mas seguro que reconciliar fila por fila: no deja
    huerfanas cuando un dia deja de corresponder (por ejemplo al cargarse una
    licencia que lo cubre).
    """
    db.execute(text("""
        DELETE FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta})

    ahora = datetime.now()
    for f in filas:
        db.execute(text("""
            INSERT INTO JornadaDiaria
                (employeeId, fecha, estado, horasRequeridas, horasTrabajadas,
                 saldoDia, entrada, salida, entradaManual, salidaManual,
                 permisoBanco, permisoDeuda, permisoOficial,
                 corregidoPor, corregidoAt, observacion, calculadoAt)
            VALUES
                (:employeeId, :fecha, :estado, :horasRequeridas, :horasTrabajadas,
                 :saldoDia, :entrada, :salida, :entradaManual, :salidaManual,
                 :permisoBanco, :permisoDeuda, :permisoOficial,
                 :corregidoPor, :corregidoAt, :observacion, :calculadoAt)
        """), {**f, "employeeId": employee_id, "calculadoAt": ahora})

    db.commit()
    return len(filas)


def saldo_acumulado(db: Session, employee_id: int) -> float:
    fila = db.execute(text(
        "SELECT COALESCE(SUM(saldoDia), 0) AS s FROM JornadaDiaria WHERE employeeId = :emp"
    ), {"emp": employee_id}).mappings().first()
    return float(fila["s"]) if fila else 0.0


def jornadas_de(db: Session, employee_id: int, desde: date, hasta: date) -> list[dict]:
    filas = db.execute(text("""
        SELECT id, fecha, estado, horasRequeridas, horasTrabajadas, saldoDia,
               entrada, salida, entradaManual, salidaManual,
               permisoBanco, permisoDeuda, permisoOficial, corregidoPor, observacion
        FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
        ORDER BY fecha DESC
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    return [dict(f) for f in filas]


def jornadas_incompletas(db: Session) -> list[dict]:
    """Jornadas que esperan intervencion de RRHH."""
    filas = db.execute(text("""
        SELECT j.id, j.employeeId, e.name AS employeeName, j.fecha, j.estado,
               j.entrada, j.salida
        FROM JornadaDiaria j
        INNER JOIN Employee e ON e.id = j.employeeId
        WHERE j.estado IN ('incompleta', 'sin_horario')
        ORDER BY j.fecha DESC, e.name ASC
    """)).mappings().all()
    return [dict(f) for f in filas]


def tablero(db: Session, desde: date, hasta: date) -> list[dict]:
    """
    Una fila por empleado vinculado a un reloj. El saldo es historico completo;
    ausencias e incompletas se cuentan solo dentro del rango consultado.
    """
    filas = db.execute(text("""
        SELECT
            e.id                AS employeeId,
            e.name              AS employeeName,
            e.biometricoId,
            COALESCE(hist.saldo, 0)        AS saldoAcumulado,
            COALESCE(rango.ausencias, 0)   AS ausencias,
            COALESCE(rango.incompletas, 0) AS incompletas
        FROM Employee e
        LEFT JOIN (
            SELECT employeeId, SUM(saldoDia) AS saldo
            FROM JornadaDiaria GROUP BY employeeId
        ) hist ON hist.employeeId = e.id
        LEFT JOIN (
            SELECT employeeId,
                   SUM(CASE WHEN estado = 'ausente'    THEN 1 ELSE 0 END) AS ausencias,
                   SUM(CASE WHEN estado = 'incompleta' THEN 1 ELSE 0 END) AS incompletas
            FROM JornadaDiaria
            WHERE fecha >= :desde AND fecha <= :hasta
            GROUP BY employeeId
        ) rango ON rango.employeeId = e.id
        WHERE e.biometricoId IS NOT NULL
        ORDER BY e.name ASC
    """), {"desde": desde, "hasta": hasta}).mappings().all()
    return [dict(f) for f in filas]


def get_jornada(db: Session, jornada_id: int) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT id, employeeId, fecha, estado,
               horasRequeridas, horasTrabajadas, saldoDia,
               entrada, salida, entradaManual, salidaManual,
               permisoBanco, permisoDeuda, permisoOficial,
               corregidoPor, observacion
        FROM JornadaDiaria WHERE id = :id
    """), {"id": jornada_id}).mappings().first()
    return dict(fila) if fila else None


def marcar_correccion(db: Session, jornada_id: int,
                      entrada: Optional[datetime], salida: Optional[datetime],
                      corregido_por: int, observacion: Optional[str]) -> None:
    """
    Persiste la carga manual. Los flags entradaManual y salidaManual son la
    fuente de verdad para el recalculo: sin ellos, la proxima corrida
    sobrescribiria la correccion con lo que dice el reloj.
    """
    db.execute(text("""
        UPDATE JornadaDiaria
        SET entrada       = COALESCE(:entrada, entrada),
            salida        = COALESCE(:salida, salida),
            entradaManual = CASE WHEN :entrada IS NOT NULL THEN 1 ELSE entradaManual END,
            salidaManual  = CASE WHEN :salida  IS NOT NULL THEN 1 ELSE salidaManual  END,
            corregidoPor  = :por,
            corregidoAt   = GETDATE(),
            observacion   = :obs
        WHERE id = :id
    """), {"entrada": entrada, "salida": salida, "por": corregido_por,
           "obs": (observacion or None), "id": jornada_id})
    db.commit()
