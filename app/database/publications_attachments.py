"""
Adjuntos de las publicaciones del Portal Institucional (subsistema 3).
Los binarios se guardan en disco (uploads/publications/), la DB guarda
solo metadatos + ruta -- nunca base64. Una sola tabla para inline
(imagenes/video/galeria embebidos en el HTML) y adjuntos descargables.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


# Limite de tamano por categoria (bytes)
CATEGORIAS_LIMITE = {
    "imagen": 10 * 1024 * 1024,
    "documento": 25 * 1024 * 1024,
    "video": 200 * 1024 * 1024,
}

EXT_A_CATEGORIA = {
    "jpg": "imagen", "jpeg": "imagen", "png": "imagen", "webp": "imagen", "gif": "imagen",
    "pdf": "documento", "docx": "documento", "xlsx": "documento", "pptx": "documento",
    "txt": "documento", "zip": "documento",
    "mp4": "video", "webm": "video",
}

VALID_ROLES = {"inline", "adjunto"}


CREATE_ATTACHMENT_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects WHERE name = 'PublicationAttachment' AND xtype = 'U'
)
BEGIN
    CREATE TABLE PublicationAttachment (
        id            INT IDENTITY(1,1) PRIMARY KEY,
        publicationId INT           NULL,
        rol           NVARCHAR(20)  NOT NULL,
        fileName      NVARCHAR(300) NOT NULL,
        storedName    NVARCHAR(300) NOT NULL,
        mimeType      NVARCHAR(100) NOT NULL,
        sizeBytes     BIGINT        NOT NULL,
        url           NVARCHAR(500) NOT NULL,
        orden         INT           NOT NULL DEFAULT 0,
        activo        BIT           NOT NULL DEFAULT 1,
        createdAt     DATETIME2     NOT NULL
    );
    CREATE INDEX IX_PublicationAttachment_publicationId ON PublicationAttachment (publicationId);
END
"""


def ensure_attachments_table(db: Session) -> None:
    """Crea PublicationAttachment si no existe (idempotente)."""
    db.execute(text(CREATE_ATTACHMENT_SQL))
    db.commit()


def categoria_de_extension(ext: str) -> str | None:
    """Devuelve 'imagen'|'documento'|'video' para la extension, o None si no permitida."""
    return EXT_A_CATEGORIA.get(ext.lower().lstrip("."))


def insertar_adjunto(db: Session, rol: str, file_name: str, stored_name: str,
                     mime_type: str, size_bytes: int, url: str) -> dict:
    """Inserta una fila de adjunto (publicationId NULL) y devuelve su metadata."""
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO PublicationAttachment
            (publicationId, rol, fileName, storedName, mimeType, sizeBytes, url, orden, activo, createdAt)
        OUTPUT INSERTED.id
        VALUES (NULL, :rol, :fileName, :storedName, :mimeType, :sizeBytes, :url, 0, 1, :createdAt)
    """), {
        "rol": rol, "fileName": file_name, "storedName": stored_name,
        "mimeType": mime_type, "sizeBytes": size_bytes, "url": url, "createdAt": now,
    })
    new_id = result.scalar()
    db.commit()
    return {"id": new_id, "url": url, "fileName": file_name, "mimeType": mime_type, "sizeBytes": size_bytes}


def adjuntos_descargables_de(db: Session, publication_id: int) -> list[dict]:
    """Adjuntos rol='adjunto' activos de una publicacion, ordenados."""
    rows = db.execute(text("""
        SELECT id, fileName, url, mimeType, sizeBytes
        FROM PublicationAttachment
        WHERE publicationId = :id AND rol = 'adjunto' AND activo = 1
        ORDER BY orden, id
    """), {"id": publication_id}).mappings().all()
    return [dict(r) for r in rows]


def asociar_adjuntos(db: Session, publication_id: int, ids: list[int]) -> None:
    """Asocia (al crear) los adjuntos indicados a la publicacion. Ignora ids invalidos."""
    for raw in ids or []:
        try:
            aid = int(raw)
        except (TypeError, ValueError):
            continue
        db.execute(text("""
            UPDATE PublicationAttachment SET publicationId = :pid, activo = 1 WHERE id = :aid
        """), {"pid": publication_id, "aid": aid})


def resync_adjuntos(db: Session, publication_id: int, ids: list[int]) -> None:
    """Re-sincroniza (al editar): asocia los de la lista y desactiva los que ya no estan."""
    limpios = []
    for raw in ids or []:
        try:
            limpios.append(int(raw))
        except (TypeError, ValueError):
            continue
    if limpios:
        placeholders = ",".join(str(i) for i in limpios)  # ints ya casteados: sin inyeccion
        db.execute(text(
            f"UPDATE PublicationAttachment SET activo = 0 "
            f"WHERE publicationId = :pid AND id NOT IN ({placeholders})"
        ), {"pid": publication_id})
        for aid in limpios:
            db.execute(text("""
                UPDATE PublicationAttachment SET publicationId = :pid, activo = 1 WHERE id = :aid
            """), {"pid": publication_id, "aid": aid})
    else:
        db.execute(text("""
            UPDATE PublicationAttachment SET activo = 0 WHERE publicationId = :pid
        """), {"pid": publication_id})


def desactivar_adjuntos_de(db: Session, publication_id: int) -> None:
    """Marca todos los adjuntos de una publicacion como inactivos (al borrar la publicacion)."""
    db.execute(text("""
        UPDATE PublicationAttachment SET activo = 0 WHERE publicationId = :id
    """), {"id": publication_id})
