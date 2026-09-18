"""
Persistencia de permisos de autorizacion: DDL idempotente, seed y consulta.

El DDL sigue el patron de app/database/marcaciones.py: se puede correr en
cada arranque sin romper nada. El seed tambien es idempotente — inserta lo
que falta y no pisa lo que el admin haya cambiado desde la UI.

Las tablas se llaman AuthPermission / AuthRolePermission y NO Permission /
RolePermission a proposito: en esta base ya existe una tabla `Permission`
de negocio, que guarda los permisos laborales de los empleados (salida y
regreso en horario de trabajo). La usan rrhh.py y asistencia_recalc.py.
Son dos conceptos distintos que comparten nombre en castellano; el prefijo
Auth evita pisar datos reales.
"""

import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.bajas import bajas_de_empleado
from app.permisos import COMODIN, DESCRIPCIONES, PERMISOS, PERMISOS_POR_ROL, recortar_por_baja
from app.services.bajas import baja_vigente

log = logging.getLogger(__name__)


def ensure_tables(db: Session) -> None:
    """Crea AuthPermission y AuthRolePermission si no existen. Seguro de repetir."""
    db.execute(text("""
        IF OBJECT_ID('dbo.AuthPermission', 'U') IS NULL
        CREATE TABLE dbo.AuthPermission (
            id          INT IDENTITY(1,1) PRIMARY KEY,
            code        NVARCHAR(64)  NOT NULL,
            description NVARCHAR(255) NULL,
            CONSTRAINT UQ_AuthPermission_code UNIQUE (code)
        )
    """))
    db.execute(text("""
        IF OBJECT_ID('dbo.AuthRolePermission', 'U') IS NULL
        CREATE TABLE dbo.AuthRolePermission (
            roleId       INT NOT NULL,
            permissionId INT NOT NULL,
            CONSTRAINT PK_AuthRolePermission PRIMARY KEY (roleId, permissionId),
            CONSTRAINT FK_AuthRolePermission_Role
                FOREIGN KEY (roleId) REFERENCES dbo.Role(id),
            CONSTRAINT FK_AuthRolePermission_Permission
                FOREIGN KEY (permissionId) REFERENCES dbo.AuthPermission(id)
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
            IF NOT EXISTS (SELECT 1 FROM AuthPermission WHERE code = :code)
            INSERT INTO AuthPermission (code, description)
            VALUES (:code, :description)
        """), {
            "code": code,
            "description": DESCRIPCIONES.get(code, "Acceso total"),
        })

    filas = db.execute(text("SELECT id, code FROM AuthPermission")).mappings().all()
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
                    SELECT 1 FROM AuthRolePermission
                    WHERE roleId = :roleId AND permissionId = :permissionId
                )
                INSERT INTO AuthRolePermission (roleId, permissionId)
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
        FROM AuthRolePermission rp
        JOIN AuthPermission p ON p.id = rp.permissionId
        WHERE rp.roleId = :roleId
    """), {"roleId": role_id}).mappings().all()
    return {f["code"] for f in filas}


def esta_de_baja(db: Session, employee_id: int | None,
                 hoy: date | None = None) -> bool:
    """Si la persona tiene hoy una baja con efecto. Sin empleado, nunca."""
    if employee_id is None:
        return False
    bajas = bajas_de_empleado(db, employee_id)
    return baja_vigente(bajas, hoy or date.today()) is not None


def permisos_efectivos(db: Session, role_id: int | None,
                       employee_id: int | None,
                       hoy: date | None = None,
                       de_baja: bool | None = None) -> set[str]:
    """
    Los permisos con los que realmente opera alguien: los del rol, recortados
    si esta de baja.

    La tienen que usar TODOS los que resuelven permisos. Hoy son dos: el
    middleware en cada request y la respuesta del login, que el frontend
    guarda en localStorage. Si solo recortara el middleware, el dado de baja
    recibiria el menu completo al loguearse y lo veria hasta la proxima
    recarga.

    Suma una consulta por request, indexada por employeeId sobre una tabla
    chica. Se elige eso antes que cachear el estado en el token: un cache
    dejaria a alguien operando con los permisos de antes hasta que expire, que
    es exactamente el modo de falla que este diseno evita.

    de_baja permite pasar el estado ya calculado (el middleware lo necesita
    tambien para el corte por ruta) y no consultar EmployeeBaja dos veces.
    """
    permisos = permisos_de_rol(db, role_id)
    if de_baja is None:
        de_baja = esta_de_baja(db, employee_id, hoy)
    return recortar_por_baja(permisos, de_baja)
