"""
Persistencia de permisos: DDL idempotente, seed y consulta.

El DDL sigue el patron de app/database/marcaciones.py: se puede correr en
cada arranque sin romper nada. El seed tambien es idempotente — inserta lo
que falta y no pisa lo que el admin haya cambiado desde la UI.
"""

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.permisos import COMODIN, DESCRIPCIONES, PERMISOS, PERMISOS_POR_ROL

log = logging.getLogger(__name__)


def ensure_tables(db: Session) -> None:
    """Crea Permission y RolePermission si no existen. Seguro de repetir."""
    db.execute(text("""
        IF OBJECT_ID('dbo.Permission', 'U') IS NULL
        CREATE TABLE dbo.Permission (
            id          INT IDENTITY(1,1) PRIMARY KEY,
            code        NVARCHAR(64)  NOT NULL,
            description NVARCHAR(255) NULL,
            CONSTRAINT UQ_Permission_code UNIQUE (code)
        )
    """))
    db.execute(text("""
        IF OBJECT_ID('dbo.RolePermission', 'U') IS NULL
        CREATE TABLE dbo.RolePermission (
            roleId       INT NOT NULL,
            permissionId INT NOT NULL,
            CONSTRAINT PK_RolePermission PRIMARY KEY (roleId, permissionId),
            CONSTRAINT FK_RolePermission_Role
                FOREIGN KEY (roleId) REFERENCES dbo.Role(id),
            CONSTRAINT FK_RolePermission_Permission
                FOREIGN KEY (permissionId) REFERENCES dbo.Permission(id)
                ON DELETE CASCADE
        )
    """))
    db.commit()


def _asegurar_roles(db: Session) -> dict[str, int]:
    """
    Crea por nombre los roles del catalogo que falten y devuelve nombre->id.

    Los ids los asigna la base; el codigo nunca los presupone. Un rol que ya
    existe conserva su id, sea cual sea.
    """
    for nombre in PERMISOS_POR_ROL:
        db.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM Role WHERE name = :name)
            INSERT INTO Role (name, description, createdAt, updatedAt)
            VALUES (:name, :description, SYSUTCDATETIME(), SYSUTCDATETIME())
        """), {"name": nombre, "description": f"Rol {nombre}"})

    filas = db.execute(text("SELECT id, name FROM Role")).mappings().all()
    return {f["name"]: f["id"] for f in filas}


def _asegurar_permisos(db: Session) -> dict[str, int]:
    """Crea los codigos que falten y devuelve code->id."""
    for code in sorted(PERMISOS) + [COMODIN]:
        db.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM Permission WHERE code = :code)
            INSERT INTO Permission (code, description)
            VALUES (:code, :description)
        """), {
            "code": code,
            "description": DESCRIPCIONES.get(code, "Acceso total"),
        })

    filas = db.execute(text("SELECT id, code FROM Permission")).mappings().all()
    return {f["code"]: f["id"] for f in filas}


def sembrar(db: Session) -> dict[str, int]:
    """
    Siembra la asignacion inicial rol->permisos.

    Solo INSERTA lo que falta: si el admin le saco un permiso a un rol desde
    la UI, este seed no se lo devuelve. Eso hace que sea seguro correrlo en
    cada arranque. Devuelve nombre_rol -> id para el log.
    """
    roles = _asegurar_roles(db)
    permisos = _asegurar_permisos(db)

    for nombre_rol, codigos in PERMISOS_POR_ROL.items():
        role_id = roles.get(nombre_rol)
        if role_id is None:
            log.warning("Rol %s no existe tras el seed, se omite", nombre_rol)
            continue
        for code in codigos:
            permission_id = permisos.get(code)
            if permission_id is None:
                log.warning("Permiso %s no existe tras el seed, se omite", code)
                continue
            db.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM RolePermission
                    WHERE roleId = :roleId AND permissionId = :permissionId
                )
                INSERT INTO RolePermission (roleId, permissionId)
                VALUES (:roleId, :permissionId)
            """), {"roleId": role_id, "permissionId": permission_id})

    db.commit()
    return roles


def permisos_de_rol(db: Session, role_id: int | None) -> set[str]:
    """
    Codigos de permiso vigentes para un rol, leidos de la base.

    Se consulta en cada request a proposito: si el admin cambia el rol de
    alguien, el cambio aplica al toque y no queda congelado en el JWT.
    """
    if role_id is None:
        return set()
    filas = db.execute(text("""
        SELECT p.code
        FROM RolePermission rp
        JOIN Permission p ON p.id = rp.permissionId
        WHERE rp.roleId = :roleId
    """), {"roleId": role_id}).mappings().all()
    return {f["code"] for f in filas}
