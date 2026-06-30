"""
Documentos adjuntos del legajo de un empleado (DNI, resoluciones,
certificados, etc.), cargados desde la pestaña "Documentos" del
modulo RRHH. El archivo se guarda como base64 en la columna fileData
-- mismo patron que ya usa Employee.photo (ProfilePictureUploader en
el frontend), sin infraestructura de almacenamiento nueva.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'EmployeeDocument' AND xtype = 'U'
)
BEGIN
    CREATE TABLE EmployeeDocument (
        id          INT IDENTITY(1,1) PRIMARY KEY,
        employeeId  INT            NOT NULL,
        tipo        NVARCHAR(100)  NOT NULL,
        descripcion NVARCHAR(500)  NULL,
        fileName    NVARCHAR(255)  NOT NULL,
        mimeType    NVARCHAR(100)  NOT NULL,
        fileData    NVARCHAR(MAX)  NOT NULL,
        activo      BIT            NOT NULL DEFAULT 1,
        createdAt   DATETIME2      NOT NULL
    );
    CREATE INDEX IX_EmployeeDocument_employeeId ON EmployeeDocument (employeeId);
END
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla EmployeeDocument si no existe."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def get_documents(db: Session, employee_id: int) -> list[dict]:
    """Lista documentos activos de un empleado, SIN fileData (liviano)."""
    rows = db.execute(text("""
        SELECT id, tipo, descripcion, fileName, mimeType, createdAt
        FROM EmployeeDocument
        WHERE employeeId = :employeeId AND activo = 1
        ORDER BY createdAt DESC
    """), {"employeeId": employee_id}).mappings().all()
    return [dict(r) for r in rows]


def get_document(db: Session, employee_id: int, document_id: int) -> dict | None:
    """Devuelve un documento completo (incluye fileData) para descarga."""
    row = db.execute(text("""
        SELECT id, tipo, descripcion, fileName, mimeType, fileData, createdAt
        FROM EmployeeDocument
        WHERE id = :id AND employeeId = :employeeId AND activo = 1
    """), {"id": document_id, "employeeId": employee_id}).mappings().first()
    return dict(row) if row else None


def save_document(db: Session, employee_id: int, tipo: str, descripcion: str | None,
                   file_name: str, mime_type: str, file_data: str) -> int:
    """Inserta un nuevo documento y retorna su id."""
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO EmployeeDocument (employeeId, tipo, descripcion, fileName, mimeType, fileData, activo, createdAt)
        OUTPUT INSERTED.id
        VALUES (:employeeId, :tipo, :descripcion, :fileName, :mimeType, :fileData, 1, :createdAt)
    """), {
        "employeeId": employee_id,
        "tipo": tipo,
        "descripcion": descripcion,
        "fileName": file_name,
        "mimeType": mime_type,
        "fileData": file_data,
        "createdAt": now,
    })
    new_id = result.scalar()
    db.commit()
    return new_id


def delete_document(db: Session, employee_id: int, document_id: int) -> bool:
    """Soft delete de un documento. Retorna False si no existia."""
    existing = db.execute(text("""
        SELECT id FROM EmployeeDocument WHERE id = :id AND employeeId = :employeeId
    """), {"id": document_id, "employeeId": employee_id}).fetchone()
    if not existing:
        return False
    db.execute(text("""
        UPDATE EmployeeDocument SET activo = 0 WHERE id = :id
    """), {"id": document_id})
    db.commit()
    return True
