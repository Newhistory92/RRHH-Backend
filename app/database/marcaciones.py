"""
Marcaciones crudas de los relojes biometricos y estado de sincronizacion.

Las marcaciones se guardan SIEMPRE, incluso si el biometricoId todavia no
corresponde a ningun empleado: quedan huerfanas y aparecen retroactivamente
cuando RRHH carga el vinculo, sin necesidad de resincronizar.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

CREATE_MARCACION_SQL = """
IF OBJECT_ID('Marcacion', 'U') IS NULL
CREATE TABLE Marcacion (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    relojIp       NVARCHAR(20)  NOT NULL,
    serialNo      BIGINT        NOT NULL,
    biometricoId  NVARCHAR(50)  NOT NULL,
    nombreReloj   NVARCHAR(100) NULL,
    fechaHora     DATETIME2     NOT NULL,
    verifyMode    NVARCHAR(30)  NULL,
    createdAt     DATETIME2     NOT NULL DEFAULT GETDATE(),
    CONSTRAINT UQ_Marcacion UNIQUE (relojIp, serialNo)
);
"""

CREATE_INDEX_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Marcacion_bio_fecha')
CREATE INDEX IX_Marcacion_bio_fecha ON Marcacion (biometricoId, fechaHora);
"""

CREATE_RELOJSYNC_SQL = """
IF OBJECT_ID('RelojSync', 'U') IS NULL
CREATE TABLE RelojSync (
    relojIp     NVARCHAR(20)  PRIMARY KEY,
    ultimaSync  DATETIME2     NULL,
    ultimoError NVARCHAR(500) NULL,
    activo      BIT           NOT NULL DEFAULT 1
);
"""

ALTER_EMPLOYEE_BIOMETRICO_SQL = """
IF COL_LENGTH('Employee','biometricoId') IS NULL
ALTER TABLE Employee ADD biometricoId NVARCHAR(50) NULL;
"""

# Indice filtrado: impide que dos empleados compartan el mismo ID del reloj
# (seria un error silencioso: dos personas viendo las mismas marcaciones),
# pero admite varios NULL para los que todavia no estan vinculados.
CREATE_UX_BIOMETRICO_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_Employee_biometricoId')
CREATE UNIQUE INDEX UX_Employee_biometricoId ON Employee (biometricoId)
WHERE biometricoId IS NOT NULL;
"""


def ensure_tables(db: Session) -> None:
    """DDL idempotente. Cada sentencia en su propio batch + commit."""
    db.execute(text(CREATE_MARCACION_SQL))
    db.commit()
    db.execute(text(CREATE_INDEX_SQL))
    db.commit()
    db.execute(text(CREATE_RELOJSYNC_SQL))
    db.commit()
    ensure_columna_biometrico(db)


def ensure_columna_biometrico(db: Session) -> None:
    """DDL idempotente de Employee.biometricoId. Cada batch con su commit."""
    db.execute(text(ALTER_EMPLOYEE_BIOMETRICO_SQL))
    db.commit()
    db.execute(text(CREATE_UX_BIOMETRICO_SQL))
    db.commit()


def registrar_reloj(db: Session, reloj_ip: str) -> None:
    """Alta idempotente en RelojSync."""
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM RelojSync WHERE relojIp = :ip)
        INSERT INTO RelojSync (relojIp, ultimaSync, ultimoError, activo)
        VALUES (:ip, NULL, NULL, 1)
    """), {"ip": reloj_ip})
    db.commit()


def estado_relojes(db: Session) -> list[dict]:
    filas = db.execute(text(
        "SELECT relojIp, ultimaSync, ultimoError, activo FROM RelojSync ORDER BY relojIp"
    )).mappings().all()
    return [dict(f) for f in filas]


def ultima_sync(db: Session, reloj_ip: str) -> Optional[datetime]:
    fila = db.execute(text(
        "SELECT ultimaSync FROM RelojSync WHERE relojIp = :ip"
    ), {"ip": reloj_ip}).mappings().first()
    return fila["ultimaSync"] if fila else None


def marcar_sync_ok(db: Session, reloj_ip: str, momento: datetime) -> None:
    db.execute(text("""
        UPDATE RelojSync SET ultimaSync = :m, ultimoError = NULL WHERE relojIp = :ip
    """), {"m": momento, "ip": reloj_ip})


def marcar_sync_error(db: Session, reloj_ip: str, error: str) -> None:
    db.execute(text("""
        UPDATE RelojSync SET ultimoError = :e WHERE relojIp = :ip
    """), {"e": error[:500], "ip": reloj_ip})


def max_serial_no(db: Session, reloj_ip: str) -> Optional[int]:
    """
    Mayor serialNo ya almacenado del equipo. Se usa para detectar un reinicio
    del correlativo, que romperia silenciosamente la idempotencia.
    """
    fila = db.execute(text(
        "SELECT MAX(serialNo) AS m FROM Marcacion WHERE relojIp = :ip"
    ), {"ip": reloj_ip}).mappings().first()
    return fila["m"] if fila and fila["m"] is not None else None


def insertar_marcaciones(db: Session, filas: list[dict]) -> int:
    """
    Inserta descartando las que ya existen por (relojIp, serialNo).

    Resuelve los existentes con UNA consulta previa por lote en lugar de
    apoyarse en el rowcount de un 'IF NOT EXISTS ... INSERT': sobre SQL Server
    ese rowcount no distingue de forma confiable el insert que ocurrio del que
    se salteo, y el conteo devuelto se usa para verificar la idempotencia.
    """
    if not filas:
        return 0

    reloj_ip = filas[0]["relojIp"]
    seriales = [f["serialNo"] for f in filas]

    # Parametrizado: se genera un bind por serial, nunca interpolacion.
    binds = {f"s{i}": s for i, s in enumerate(seriales)}
    marcadores = ", ".join(f":{k}" for k in binds)
    existentes = {
        r["serialNo"]
        for r in db.execute(text(
            f"SELECT serialNo FROM Marcacion WHERE relojIp = :ip AND serialNo IN ({marcadores})"
        ), {"ip": reloj_ip, **binds}).mappings().all()
    }

    nuevas = [f for f in filas if f["serialNo"] not in existentes]
    ahora = datetime.now()
    insertadas = 0
    for f in nuevas:
        try:
            db.execute(text("""
                INSERT INTO Marcacion
                    (relojIp, serialNo, biometricoId, nombreReloj, fechaHora, verifyMode, createdAt)
                VALUES
                    (:relojIp, :serialNo, :biometricoId, :nombreReloj, :fechaHora, :verifyMode, :createdAt)
            """), {**f, "createdAt": ahora})
            insertadas += 1
        except IntegrityError:
            # Race condition: otro proceso insertó el mismo (relojIp, serialNo) entre
            # nuestra query de dedup y este insert. Rollback + continuar.
            db.rollback()

    db.commit()
    return insertadas


def marcaciones_de(db: Session, biometrico_id: str,
                   desde: datetime, hasta: datetime) -> list[dict]:
    filas = db.execute(text("""
        SELECT id, relojIp, serialNo, biometricoId, nombreReloj, fechaHora, verifyMode
        FROM Marcacion
        WHERE biometricoId = :bio AND fechaHora >= :desde AND fechaHora <= :hasta
        ORDER BY fechaHora
    """), {"bio": str(biometrico_id), "desde": desde, "hasta": hasta}).mappings().all()
    return [dict(f) for f in filas]
