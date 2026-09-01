"""
Cumplimiento horario como dimension de la ficha de merito.

Se mide por recurrencia, no por minutos acumulados: sumar minutos castiga
igual una demora puntual que un patron sostenido, y solo el segundo dice algo
del desempeno. El motor de asistencia ya calcula la senal correcta en el flag
abusoEntrada -quien se recuesta sistematicamente sobre el margen de tolerancia
sin llegar a excederlo-, asi que aca solo se agrega sobre los dias trabajados.

Es la unica dimension comparable entre todas las funciones por igual: no
depende de que el trabajo de la persona pase por ningun sistema.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Cumplimiento:
    diasTrabajados: int
    diasConAbuso: int
    tasaAbuso: float | None


def tasa_abuso(dias_con_abuso: int, dias_trabajados: int) -> float | None:
    """
    Proporcion de dias con abuso de tolerancia sobre los dias trabajados.

    Sin dias trabajados no hay tasa: seria dividir por cero, y devolver 0.0
    diria "cumplimiento perfecto" de alguien a quien no se midio.

    Funcion pura, sin I/O.
    """
    if dias_trabajados <= 0:
        return None
    return round(dias_con_abuso / dias_trabajados, 2)


def cumplimiento_por_empleado(db: Session, meses: int = 12) -> dict[int, Cumplimiento]:
    """
    Dias trabajados y dias con abuso de entrada por empleado, en la ventana.

    Solo cuenta jornadas con horas cargadas: un dia de licencia no es un dia
    trabajado y no debe engrosar el denominador, porque bajaria artificialmente
    la tasa de quien estuvo ausente con derecho.
    """
    filas = db.execute(text("""
        SELECT employeeId,
               COUNT(*) AS dias,
               SUM(CASE WHEN abusoEntrada = 1 THEN 1 ELSE 0 END) AS abusos
        FROM JornadaDiaria
        WHERE fecha >= DATEADD(MONTH, -:meses, GETDATE())
          AND horasTrabajadas IS NOT NULL
          AND horasTrabajadas > 0
        GROUP BY employeeId
    """), {"meses": meses}).mappings().all()

    return {
        int(f["employeeId"]): Cumplimiento(
            diasTrabajados=int(f["dias"]),
            diasConAbuso=int(f["abusos"] or 0),
            tasaAbuso=tasa_abuso(int(f["abusos"] or 0), int(f["dias"])),
        )
        for f in filas
    }
