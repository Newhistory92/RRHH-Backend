"""
Persistencia de las justificaciones de ausencia.

Una fila por dia justificado. La tabla es un insumo del recalculo, igual que
JornadaCorreccion: el motor la lee y reconstruye el estado del dia. Por eso no
guarda nada calculado.
"""

from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

TIPO_DOCUMENTO = "Parte médico"

CREATE_TABLE_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='JornadaJustificacion' AND xtype='U')
BEGIN
    CREATE TABLE JornadaJustificacion (
        id             INT IDENTITY(1,1) PRIMARY KEY,
        employeeId     INT           NOT NULL,
        fecha          DATE          NOT NULL,
        documentoId    INT           NOT NULL,
        observacion    NVARCHAR(500) NULL,
        justificadoPor INT           NOT NULL,
        createdAt      DATETIME2     NOT NULL,
        CONSTRAINT UQ_JornadaJustificacion UNIQUE (employeeId, fecha)
    );
    CREATE INDEX IX_JornadaJustificacion_empleado
        ON JornadaJustificacion (employeeId, fecha);
END
"""


def ensure_tables(db: Session) -> None:
    """Crea la tabla si no existe. Idempotente."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def justificar(db: Session, employee_id: int, fecha: date, file_name: str,
               mime_type: str, file_data: str, observacion: str | None,
               justificado_por: int) -> int:
    """
    Guarda el parte medico y la justificacion del dia en una sola transaccion.
    Devuelve el id del documento nuevo.

    Si el dia ya estaba justificado, reemplaza el parte y da de baja el
    anterior: es la carga de un documento corregido, no un duplicado.

    El INSERT del documento se hace aca y no con employee_documents.save_document
    porque aquella funcion commitea por su cuenta, y un fallo posterior en el
    upsert dejaria un documento huerfano.
    """
    ahora = datetime.utcnow()

    documento_id = db.execute(text("""
        INSERT INTO EmployeeDocument
            (employeeId, tipo, descripcion, fileName, mimeType, fileData,
             activo, createdAt)
        OUTPUT INSERTED.id
        VALUES (:emp, :tipo, :desc, :nombre, :mime, :datos, 1, :ahora)
    """), {
        "emp": employee_id, "tipo": TIPO_DOCUMENTO,
        "desc": f"Justificacion de la ausencia del {fecha.isoformat()}",
        "nombre": file_name, "mime": mime_type, "datos": file_data,
        "ahora": ahora,
    }).scalar()

    previa = db.execute(text("""
        SELECT documentoId FROM JornadaJustificacion
        WHERE employeeId = :emp AND fecha = :fecha
    """), {"emp": employee_id, "fecha": fecha}).mappings().first()

    if previa is None:
        db.execute(text("""
            INSERT INTO JornadaJustificacion
                (employeeId, fecha, documentoId, observacion, justificadoPor,
                 createdAt)
            VALUES (:emp, :fecha, :doc, :obs, :por, :ahora)
        """), {"emp": employee_id, "fecha": fecha, "doc": documento_id,
               "obs": observacion, "por": justificado_por, "ahora": ahora})
    else:
        db.execute(text("""
            UPDATE JornadaJustificacion
            SET documentoId = :doc, observacion = :obs, justificadoPor = :por,
                createdAt = :ahora
            WHERE employeeId = :emp AND fecha = :fecha
        """), {"emp": employee_id, "fecha": fecha, "doc": documento_id,
               "obs": observacion, "por": justificado_por, "ahora": ahora})
        db.execute(text("""
            UPDATE EmployeeDocument SET activo = 0 WHERE id = :id
        """), {"id": previa["documentoId"]})

    db.commit()
    return int(documento_id)


def borrar_justificacion(db: Session, employee_id: int, fecha: date) -> bool:
    """
    Anula la justificacion y da de baja su documento. Devuelve False si no
    habia ninguna.
    """
    fila = db.execute(text("""
        SELECT documentoId FROM JornadaJustificacion
        WHERE employeeId = :emp AND fecha = :fecha
    """), {"emp": employee_id, "fecha": fecha}).mappings().first()
    if fila is None:
        return False

    db.execute(text("""
        DELETE FROM JornadaJustificacion
        WHERE employeeId = :emp AND fecha = :fecha
    """), {"emp": employee_id, "fecha": fecha})
    db.execute(text("""
        UPDATE EmployeeDocument SET activo = 0 WHERE id = :id
    """), {"id": fila["documentoId"]})
    db.commit()
    return True


def dias_justificados(db: Session, employee_id: int,
                      desde: date, hasta: date) -> set[date]:
    """Las fechas justificadas del rango. Es el insumo del recalculo."""
    filas = db.execute(text("""
        SELECT fecha FROM JornadaJustificacion
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    return {f["fecha"].date() if isinstance(f["fecha"], datetime) else f["fecha"]
            for f in filas}


def justificaciones_de(db: Session, employee_id: int, desde: date,
                       hasta: date) -> dict[date, dict]:
    """
    El detalle de cada justificacion del rango, indexado por fecha. Trae los
    datos del documento y el nombre de quien justifico, que es lo que muestra
    la pestana de Ausencias.
    """
    filas = db.execute(text("""
        SELECT j.fecha, j.documentoId, j.observacion, j.createdAt,
               d.fileName, d.mimeType, e.name AS justificadoPor
        FROM JornadaJustificacion j
        LEFT JOIN EmployeeDocument d ON d.id = j.documentoId
        LEFT JOIN Employee e ON e.id = j.justificadoPor
        WHERE j.employeeId = :emp AND j.fecha >= :desde AND j.fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()

    detalle: dict[date, dict] = {}
    for f in filas:
        d = f["fecha"].date() if isinstance(f["fecha"], datetime) else f["fecha"]
        detalle[d] = {
            "documentoId": int(f["documentoId"]),
            "fileName": f["fileName"],
            "mimeType": f["mimeType"],
            "observacion": f["observacion"],
            "justificadoPor": f["justificadoPor"] or "",
            "createdAt": f["createdAt"].isoformat() if f["createdAt"] else None,
        }
    return detalle
