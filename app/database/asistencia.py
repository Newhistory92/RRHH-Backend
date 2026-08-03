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

from app.database.asistencia_auditoria import (
    ensure_tables as auditoria_ensure_tables,
    reemplazar_incidencias,
)

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

ALTER_TOLERANCIA_ENTRADA_SQL = """
IF COL_LENGTH('JornadaDiaria','toleranciaEntradaUsada') IS NULL
ALTER TABLE JornadaDiaria ADD toleranciaEntradaUsada BIT NOT NULL DEFAULT 0;
"""

ALTER_TOLERANCIA_SALIDA_SQL = """
IF COL_LENGTH('JornadaDiaria','toleranciaSalidaUsada') IS NULL
ALTER TABLE JornadaDiaria ADD toleranciaSalidaUsada BIT NOT NULL DEFAULT 0;
"""

# Columnas que dejaron de ser derivadas: se mudaron a JornadaCorreccion.
# entradaManual y salidaManual se conservan porque si son derivadas -se
# reconstruyen leyendo JornadaCorreccion- y evitan un join en cada lectura.
COLUMNAS_A_ELIMINAR = ("corregidoPor", "corregidoAt", "observacion")


def _drop_columna(db: Session, tabla: str, columna: str) -> None:
    """
    Suelta el constraint de default antes de borrar la columna: SQL Server no
    permite eliminar una columna con default sin quitarlo primero.

    tabla y columna son constantes del propio codigo, nunca entrada del
    usuario: la interpolacion no expone inyeccion.
    """
    db.execute(text(f"""
        IF COL_LENGTH('{tabla}','{columna}') IS NOT NULL
        BEGIN
            DECLARE @c NVARCHAR(200);
            SELECT @c = dc.name
            FROM sys.default_constraints dc
            JOIN sys.columns c ON c.object_id = dc.parent_object_id
                              AND c.column_id = dc.parent_column_id
            WHERE dc.parent_object_id = OBJECT_ID('{tabla}')
              AND c.name = '{columna}';
            IF @c IS NOT NULL
                EXEC('ALTER TABLE {tabla} DROP CONSTRAINT ' + @c);
            ALTER TABLE {tabla} DROP COLUMN {columna};
        END
    """))
    db.commit()


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
    db.execute(text(ALTER_TOLERANCIA_ENTRADA_SQL))
    db.commit()
    db.execute(text(ALTER_TOLERANCIA_SALIDA_SQL))
    db.commit()
    for columna in COLUMNAS_A_ELIMINAR:
        _drop_columna(db, "JornadaDiaria", columna)
    db.execute(text(SEED_CONFIG_SQL))
    db.commit()
    auditoria_ensure_tables(db)


def get_config(db: Session) -> dict:
    fila = db.execute(text("""
        SELECT toleranciaEntradaMin, toleranciaSalidaMin, fechaInicioModulo
        FROM AsistenciaConfig WHERE id = 1
    """)).mappings().first()
    if fila is None:
        return {"toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
                "fechaInicioModulo": date.today()}
    return dict(fila)


def update_config(db: Session, tol_entrada: int, tol_salida: int,
                  fecha_inicio: Optional[date] = None) -> dict:
    """
    fecha_inicio en None deja la que estaba. Se puede mover hacia atras cuando
    se recupera historico de los relojes, y hacia adelante para descartar un
    periodo poco confiable.
    """
    db.execute(text("""
        UPDATE AsistenciaConfig
        SET toleranciaEntradaMin = :te,
            toleranciaSalidaMin  = :ts,
            fechaInicioModulo    = COALESCE(:fi, fechaInicioModulo),
            updatedAt            = GETDATE()
        WHERE id = 1
    """), {"te": int(tol_entrada), "ts": int(tol_salida), "fi": fecha_inicio})
    db.commit()
    return get_config(db)


def reemplazar_jornadas(db: Session, employee_id: int, desde: date, hasta: date,
                        filas: list[dict], incidencias: list[dict]) -> int:
    """
    Borra el rango del empleado y reinserta jornadas e incidencias en la misma
    transaccion. Las dos son derivadas, asi que reemplazar es mas simple y mas
    seguro que reconciliar fila por fila: no deja huerfanas cuando un dia deja
    de corresponder (por ejemplo al cargarse una licencia que lo cubre).

    JornadaCorreccion no se toca: es dato propio y vive en su tabla.
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
                 toleranciaEntradaUsada, toleranciaSalidaUsada, calculadoAt)
            VALUES
                (:employeeId, :fecha, :estado, :horasRequeridas, :horasTrabajadas,
                 :saldoDia, :entrada, :salida, :entradaManual, :salidaManual,
                 :permisoBanco, :permisoDeuda, :permisoOficial,
                 :toleranciaEntradaUsada, :toleranciaSalidaUsada, :calculadoAt)
        """), {**f, "employeeId": employee_id, "calculadoAt": ahora})

    reemplazar_incidencias(db, employee_id, desde, hasta, incidencias)
    db.commit()
    return len(filas)


def saldo_acumulado(db: Session, employee_id: int) -> float:
    fila = db.execute(text(
        "SELECT COALESCE(SUM(saldoDia), 0) AS s FROM JornadaDiaria WHERE employeeId = :emp"
    ), {"emp": employee_id}).mappings().first()
    return float(fila["s"]) if fila else 0.0


def jornadas_de(db: Session, employee_id: int, desde: date, hasta: date) -> list[dict]:
    """Jornadas del rango con sus incidencias agregadas como lista."""
    filas = db.execute(text("""
        SELECT j.id, j.fecha, j.estado, j.horasRequeridas, j.horasTrabajadas,
               j.saldoDia, j.entrada, j.salida, j.entradaManual, j.salidaManual,
               j.permisoBanco, j.permisoDeuda, j.permisoOficial,
               j.toleranciaEntradaUsada, j.toleranciaSalidaUsada,
               c.corregidoPor, c.observacion
        FROM JornadaDiaria j
        LEFT JOIN JornadaCorreccion c
               ON c.employeeId = j.employeeId AND c.fecha = j.fecha
        WHERE j.employeeId = :emp AND j.fecha >= :desde AND j.fecha <= :hasta
        ORDER BY j.fecha DESC
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()

    incidencias = db.execute(text("""
        SELECT fecha, tipo FROM JornadaIncidencia
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    por_dia: dict[date, list[str]] = {}
    for i in incidencias:
        d = i["fecha"] if isinstance(i["fecha"], date) else i["fecha"].date()
        por_dia.setdefault(d, []).append(i["tipo"])

    salida = []
    for f in filas:
        d = f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
        salida.append({**dict(f), "incidencias": por_dia.get(d, [])})
    return salida


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
        SELECT j.id, j.employeeId, j.fecha, j.estado,
               j.horasRequeridas, j.horasTrabajadas, j.saldoDia,
               j.entrada, j.salida, j.entradaManual, j.salidaManual,
               j.permisoBanco, j.permisoDeuda, j.permisoOficial,
               j.toleranciaEntradaUsada, j.toleranciaSalidaUsada,
               c.corregidoPor, c.observacion
        FROM JornadaDiaria j
        LEFT JOIN JornadaCorreccion c
               ON c.employeeId = j.employeeId AND c.fecha = j.fecha
        WHERE j.id = :id
    """), {"id": jornada_id}).mappings().first()
    return dict(fila) if fila else None
