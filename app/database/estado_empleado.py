"""
El estado de Employee.status que corresponde a quien esta trabajando.

Lo comparten _sync_employee_status (app/routes/licenses.py) y la vuelta de una
baja (app/database/bajas.py). Vive aparte para que los dos lo usen sin
importarse entre si: licenses.py ya importa bajas.py.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

ESTADO_ACTIVO = "Activo"
ESTADO_LICENCIA = "Licencia"


def estado_segun_licencias(db: Session, employee_id: int) -> str:
    """'Licencia' si hoy esta dentro de una licencia aprobada; si no, 'Activo'."""
    active_lic = db.execute(text("""
        SELECT id FROM License
        WHERE employeeId = :empId
          AND status = 'Aprobada'
          AND CAST(startDate AS DATE) <= CAST(GETDATE() AS DATE)
          AND CAST(endDate AS DATE) >= CAST(GETDATE() AS DATE)
    """), {"empId": employee_id}).first()
    return ESTADO_LICENCIA if active_lic else ESTADO_ACTIVO
