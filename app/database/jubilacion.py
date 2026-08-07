"""
Persistencia de la jubilacion.

La fecha en CondicionLaboral es la fuente de verdad. Employee.status y
User.activo son cache derivado: aplicar_jubilacion es el unico lugar que los
escribe, y lo hace siempre junto con la fecha y en la misma transaccion.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.jubilacion import jubilacion_cumplida

ESTADO_JUBILADO = "Jubilado"
ESTADO_ACTIVO = "Activo"

ALTER_FECHA_JUBILACION_SQL = """
IF COL_LENGTH('CondicionLaboral','fechaJubilacion') IS NULL
ALTER TABLE CondicionLaboral ADD fechaJubilacion DATE NULL;
"""


def ensure_columna_jubilacion(db: Session) -> None:
    """DDL idempotente de CondicionLaboral.fechaJubilacion."""
    db.execute(text(ALTER_FECHA_JUBILACION_SQL))
    db.commit()


def _a_date(valor) -> Optional[date]:
    """
    Normaliza lo que devuelve pyodbc a un date limpio.

    datetime hereda de date, asi que hay que chequear el tipo mas especifico
    primero: el guard invertido ya rompio una vez en este repo.
    """
    if valor is None:
        return None
    return valor.date() if isinstance(valor, datetime) else valor


def fecha_jubilacion_de(db: Session, employee_id: int) -> Optional[date]:
    """La fecha cargada, sin importar si ya se cumplio."""
    fila = db.execute(text("""
        SELECT MAX(fechaJubilacion) AS fecha
        FROM CondicionLaboral WHERE employeeId = :id
    """), {"id": employee_id}).mappings().first()
    return _a_date(fila["fecha"]) if fila else None


def aplicar_jubilacion(db: Session, employee_id: int, fecha: Optional[date],
                       hoy: date) -> bool:
    """
    Guarda la fecha y sincroniza el estado derivado. Devuelve True si el
    empleado quedo jubilado.

    fecha=None revierte: el empleado vuelve a Activo y recupera el acceso. Es
    el caso del error de carga, que es el mas comun.

    Una fecha futura se guarda pero no desactiva nada todavia; el job diario la
    aplica cuando llega el dia.

    Las tres escrituras van en una sola transaccion: si la fecha se guardara y
    el estado no, quedaria un jubilado con acceso al sistema.
    """
    existe = db.execute(text(
        "SELECT id FROM CondicionLaboral WHERE employeeId = :id"
    ), {"id": employee_id}).first()

    if existe:
        db.execute(text("""
            UPDATE CondicionLaboral SET fechaJubilacion = :fecha
            WHERE employeeId = :id
        """), {"fecha": fecha, "id": employee_id})
    else:
        db.execute(text("""
            INSERT INTO CondicionLaboral (employeeId, fechaJubilacion)
            VALUES (:id, :fecha)
        """), {"id": employee_id, "fecha": fecha})

    jubilado = jubilacion_cumplida(fecha, hoy)
    estado = ESTADO_JUBILADO if jubilado else ESTADO_ACTIVO
    activo = 0 if jubilado else 1

    db.execute(text("UPDATE Employee SET status = :e WHERE id = :id"),
               {"e": estado, "id": employee_id})
    # Un empleado puede no tener usuario: el UPDATE afecta cero filas y esta bien.
    db.execute(text("UPDATE [User] SET activo = :a WHERE employeeId = :id"),
               {"a": activo, "id": employee_id})

    db.commit()
    return jubilado


def pendientes_de_jubilar(db: Session, hoy: date) -> list[int]:
    """
    Empleados con fecha cumplida que todavia figuran activos.

    Es lo que consume el job diario. La consulta ya filtra por fecha para no
    traer el padron entero, pero la decision final la toma jubilacion_cumplida
    sobre cada fila: una sola definicion de "ya esta jubilado".
    """
    filas = db.execute(text("""
        SELECT e.id, c.fechaJubilacion
        FROM Employee e
        JOIN CondicionLaboral c ON c.employeeId = e.id
        WHERE c.fechaJubilacion IS NOT NULL
          AND c.fechaJubilacion <= :hoy
          AND e.status <> :jubilado
    """), {"hoy": hoy, "jubilado": ESTADO_JUBILADO}).mappings().all()
    return [int(f["id"]) for f in filas
            if jubilacion_cumplida(_a_date(f["fechaJubilacion"]), hoy)]


def jubilados(db: Session) -> list[dict]:
    """
    Los empleados con la jubilacion ya efectiva, para el tablero propio.

    Trae el saldo congelado: como el recalculo no genera dias posteriores a la
    fecha, la ultima jornada calculada es la del dia de la jubilacion.
    """
    filas = db.execute(text("""
        SELECT e.id, e.name, e.dni, e.email, e.photo, e.status,
               d.nombre AS departamento, o.nombre AS oficina,
               c.tipoContrato, c.fechaIngreso, c.fechaJubilacion,
               -- El saldo acumulado no es una columna: es la suma de los dias.
               -- Mismo calculo que saldo_acumulado() en app/database/asistencia.py.
               (SELECT COALESCE(SUM(j.saldoDia), 0) FROM JornadaDiaria j
                WHERE j.employeeId = e.id) AS saldoFinal
        FROM Employee e
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN CondicionLaboral c ON c.employeeId = e.id
        WHERE e.status = :jubilado
        ORDER BY c.fechaJubilacion DESC, e.name ASC
    """), {"jubilado": ESTADO_JUBILADO}).mappings().all()

    return [{
        "id": int(f["id"]),
        "name": f["name"],
        "dni": f["dni"],
        "email": f["email"],
        "photo": f["photo"],
        "status": f["status"],
        "departamento": f["departamento"],
        "oficina": f["oficina"],
        "tipoContrato": f["tipoContrato"],
        "fechaIngreso": _a_date(f["fechaIngreso"]).isoformat()
                        if f["fechaIngreso"] else None,
        "fechaJubilacion": _a_date(f["fechaJubilacion"]).isoformat()
                           if f["fechaJubilacion"] else None,
        "saldoFinal": float(f["saldoFinal"]) if f["saldoFinal"] is not None else 0.0,
    } for f in filas]
