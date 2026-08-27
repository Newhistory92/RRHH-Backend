"""
Marca de exencion del score de productividad.

El score sale de contar sesiones de acceso al sistema (ver stats.py). Las areas
cuyo trabajo no pasa por el sistema -- Sistemas, mantenimiento -- generan pocos
logs o ninguno, asi que siempre quedan en 0 y ultimas en el ranking, sin que eso
diga nada sobre cuanto trabajan. Marcar el area exime a su gente de esa metrica
y les asigna el promedio de los demas (ver sync_productivity_scores).

Se marca en Department y en Office: un empleado queda exento si cualquiera de
las dos lo esta. Hoy Office esta vacia en esta base, pero la columna se agrega
igual para que funcione cuando se carguen oficinas.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_columnas_exencion(db: Session) -> None:
    """Agrega scoreExento a Department y Office. Seguro de repetir."""
    db.execute(text(
        "IF COL_LENGTH('Department','scoreExento') IS NULL "
        "ALTER TABLE Department ADD scoreExento BIT NOT NULL DEFAULT 0;"
    ))
    db.execute(text(
        "IF COL_LENGTH('Office','scoreExento') IS NULL "
        "ALTER TABLE Office ADD scoreExento BIT NOT NULL DEFAULT 0;"
    ))
    db.commit()


def empleados_exentos(db: Session) -> set[int]:
    """
    Ids de empleados cuyo departamento u oficina esta marcado como exento.

    El LEFT JOIN es a proposito: un empleado sin oficina (el caso normal en
    esta base) sigue siendo evaluable por su departamento.
    """
    filas = db.execute(text("""
        SELECT e.id
        FROM Employee e
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        WHERE ISNULL(d.scoreExento, 0) = 1 OR ISNULL(o.scoreExento, 0) = 1
    """)).mappings().all()
    return {f["id"] for f in filas}
