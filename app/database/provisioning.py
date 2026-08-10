"""
Lecturas y escrituras sobre la base de RRHH necesarias para dar de alta
automaticamente a un usuario que viene de un sistema externo.

Este modulo no sabe nada de ObraSocial: recibe datos ya mapeados. Eso lo
deja reutilizable si algun dia se suma otra fuente de identidad.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

ROLE_USER = 2
ORIGEN_LOCAL = "local"
ORIGEN_OBRASOCIAL = "obrasocial"


def ensure_columna_origen(db: Session) -> None:
    """
    Marca de que sistema vino cada usuario.

    Sin esta columna un admin creado a mano en RRHH -- que no existe en la
    base externa -- quedaria bloqueado por la verificacion de bajas.
    """
    db.execute(text(
        "IF COL_LENGTH('[User]','origen') IS NULL "
        "ALTER TABLE [User] ADD origen NVARCHAR(20) NOT NULL DEFAULT 'local';"
    ))
    db.commit()


# -- Lecturas -----------------------------------------------------------------

def buscar_user(db: Session, usuario: str) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT id, usuario, email, password, roleId, employeeId, activo, origen
        FROM [User]
        WHERE usuario = :u OR email = :u
    """), {"u": usuario}).mappings().first()
    return dict(fila) if fila else None


def buscar_employee_por_dni(db: Session, dni: str) -> Optional[dict]:
    fila = db.execute(text(
        "SELECT id, dni, name FROM Employee WHERE dni = :dni"
    ), {"dni": dni}).mappings().first()
    return dict(fila) if fila else None


def employees_por_dni(db: Session, dnis: list[str]) -> dict[str, int]:
    """
    {dni: employeeId} para los DNIs que ya existen en RRHH.

    Se divide en bloques de 500 para no superar el limite de parametros de
    pyodbc/SQL Server (~2100). En la practica la lista de empleados de la
    institucion raramente supera esa cifra, pero es mas robusto dividirla.
    """
    if not dnis:
        return {}
    resultado: dict[str, int] = {}
    chunk_size = 500
    for offset in range(0, len(dnis), chunk_size):
        chunk = dnis[offset: offset + chunk_size]
        binds = {f"d{i}": valor for i, valor in enumerate(chunk)}
        marcadores = ", ".join(f":{clave}" for clave in binds)
        filas = db.execute(text(
            f"SELECT id, dni FROM Employee WHERE dni IN ({marcadores})"
        ), binds).mappings().all()
        resultado.update({str(f["dni"]).strip(): f["id"] for f in filas})
    return resultado


def email_ocupado(db: Session, email: str) -> bool:
    fila = db.execute(text(
        "SELECT id FROM Employee WHERE email = :email"
    ), {"email": email}).mappings().first()
    return fila is not None


def user_de_employee(db: Session, employee_id: int) -> Optional[dict]:
    """El [User] ya vinculado a ese empleado, si existe."""
    fila = db.execute(text(
        "SELECT id, usuario FROM [User] WHERE employeeId = :id"
    ), {"id": employee_id}).mappings().first()
    return dict(fila) if fila else None


# -- Escrituras ---------------------------------------------------------------

def crear_employee(db: Session, datos: dict) -> int:
    """
    Alta minima: solo los datos que la fuente externa conoce. Departamento,
    oficina, puesto y horario los completa RRHH despues.
    """
    resultado = db.execute(text("""
        INSERT INTO Employee (dni, name, email, gender, phone, birthDate, photo, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:dni, :name, :email, :gender, :phone, :birthDate, :photo, :updatedAt)
    """), {**datos, "updatedAt": datetime.now()})
    nuevo_id = resultado.scalar()
    db.commit()
    return nuevo_id


def id_es_identity(db: Session, tabla: str) -> bool:
    """
    Si la PK se autogenera o la tiene que calcular el llamador.

    Employee.id es IDENTITY pero [User].id no lo es en este esquema, asi que
    no se puede asumir lo mismo para las dos tablas.
    """
    fila = db.execute(text(
        "SELECT COLUMNPROPERTY(OBJECT_ID(:tabla), 'id', 'IsIdentity') AS es_identity"
    ), {"tabla": tabla}).mappings().first()
    return bool(fila and fila["es_identity"])


def crear_user(db: Session, usuario: str, email: str, password_hash: str,
               employee_id: int, origen: str, role_id: int = ROLE_USER) -> int:
    """
    El hash llega ya calculado. Cuando viene de un sistema externo que tambien
    usa bcrypt se copia tal cual, y el usuario nunca resetea su contrasena.

    Si [User].id no es IDENTITY se calcula con MAX(id)+1 dentro del mismo
    INSERT ... SELECT, para que el calculo y la escritura compartan la misma
    sentencia y dos importaciones simultaneas no elijan el mismo numero.
    """
    params = {
        "usuario": usuario,
        "email": email,
        "password": password_hash,
        "roleId": role_id,
        "employeeId": employee_id,
        "origen": origen,
    }

    if id_es_identity(db, "[User]"):
        sql = """
            INSERT INTO [User] (usuario, email, password, roleId, employeeId, origen, activo, updatedAt)
            OUTPUT INSERTED.id
            VALUES (:usuario, :email, :password, :roleId, :employeeId, :origen, 1, GETDATE())
        """
    else:
        sql = """
            INSERT INTO [User] (id, usuario, email, password, roleId, employeeId, origen, activo, updatedAt)
            OUTPUT INSERTED.id
            SELECT ISNULL(MAX(id), 0) + 1, :usuario, :email, :password, :roleId,
                   :employeeId, :origen, 1, GETDATE()
            FROM [User] WITH (TABLOCKX)
        """

    nuevo_id = db.execute(text(sql), params).scalar()
    db.commit()
    return nuevo_id


def actualizar_password(db: Session, user_id: int, password_hash: str) -> None:
    """Sincroniza el hash local cuando cambio en el sistema de origen."""
    db.execute(text(
        "UPDATE [User] SET password = :p WHERE id = :id"
    ), {"p": password_hash, "id": user_id})
    db.commit()
