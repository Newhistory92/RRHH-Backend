"""
Ausencias de un empleado y su justificacion.

Dos vias llegan al mismo lugar. Por licencia: RRHH carga y aprueba una licencia
que cubre la fecha, y el dia deja de ser una ausencia en el proximo recalculo
sin que nadie toque nada de este router. Por parte medico: RRHH adjunta el
documento aca y el dia pasa a estado justificada.
"""

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import (
    get_current_user, require_permission,
)
from app.database.asistencia import ensure_tables as ensure_tablas_asistencia
from app.database.asistencia_justificaciones import (
    borrar_justificacion, ensure_tables, justificaciones_de, justificar,
)
from app.database.database import SessionLocal
from app.services.asistencia_calc import ESTADO_AUSENTE, ESTADO_JUSTIFICADA
from app.services.asistencia_justificaciones import (
    VENTANA_JUSTIFICACION_DIAS, validar_fecha_justificable,
)
from app.services.asistencia_recalc import recalcular_anio

router = APIRouter(prefix="/asistencia", tags=["Asistencia"])

GESTIONAR_ASISTENCIA = Depends(require_permission("asistencia.gestionar"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _rango(desde: str | None, hasta: str | None) -> tuple[date, date]:
    """Sin parametros devuelve el anio en curso."""
    hoy = date.today()
    try:
        d = date.fromisoformat(desde) if desde else date(hoy.year, 1, 1)
        h = date.fromisoformat(hasta) if hasta else hoy
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Formato de fecha invalido, use YYYY-MM-DD")
    if d > h:
        raise HTTPException(status_code=400,
                            detail="'desde' no puede ser posterior a 'hasta'")
    return d, h


def _fecha(crudo: str) -> date:
    try:
        return date.fromisoformat(crudo)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="La fecha debe ser YYYY-MM-DD")


def _licencias_sin_aprobar(db: Session, employee_id: int,
                           desde: date, hasta: date) -> list[dict]:
    """
    Licencias que cubren dias del rango pero todavia no estan aprobadas.

    Es lo que hace accionable la via licencia: RRHH ve la ausencia, ve que hay
    una licencia sin aprobar que la cubriria, la aprueba, y la ausencia se
    resuelve sola en el recalculo.
    """
    filas = db.execute(text("""
        SELECT id, type, status, startDate, endDate
        FROM License
        WHERE employeeId = :emp AND status <> 'Aprobada'
          AND startDate <= :hasta AND endDate >= :desde
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    return [dict(f) for f in filas]


def _licencia_que_cubre(licencias: list[dict], dia: date) -> dict | None:
    for lic in licencias:
        ini = lic["startDate"]
        fin = lic["endDate"]
        ini = ini if isinstance(ini, date) else ini.date()
        fin = fin if isinstance(fin, date) else fin.date()
        if ini <= dia <= fin:
            return {"id": int(lic["id"]), "type": lic["type"],
                    "status": lic["status"]}
    return None


@router.get("/empleado/{employee_id}/ausencias", dependencies=[GESTIONAR_ASISTENCIA])
def get_ausencias(employee_id: int, desde: str | None = None,
                  hasta: str | None = None, db: Session = Depends(get_db)):
    """
    Los dias ausentes y justificados del rango.

    Los dias de licencia no aparecen: nunca fueron un problema a resolver. Que
    una ausencia desaparezca de esta lista es justamente la confirmacion de que
    la licencia retroactiva quedo aprobada.
    """
    ensure_tablas_asistencia(db)
    ensure_tables(db)
    d, h = _rango(desde, hasta)
    hoy = date.today()

    filas = db.execute(text("""
        SELECT fecha, estado, horasRequeridas
        FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
          AND estado IN (:ausente, :justificada)
        ORDER BY fecha DESC
    """), {"emp": employee_id, "desde": d, "hasta": h,
           "ausente": ESTADO_AUSENTE, "justificada": ESTADO_JUSTIFICADA}
    ).mappings().all()

    detalle = justificaciones_de(db, employee_id, d, h)
    pendientes = _licencias_sin_aprobar(db, employee_id, d, h)

    ausencias = []
    for f in filas:
        dia = f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
        justificada = f["estado"] == ESTADO_JUSTIFICADA
        puede = True
        try:
            validar_fecha_justificable(dia, hoy)
        except ValueError:
            puede = False
        ausencias.append({
            "fecha": dia.isoformat(),
            "estado": f["estado"],
            "horasPerdidas": float(f["horasRequeridas"] or 0),
            "puedeJustificar": puede,
            "justificacion": detalle.get(dia),
            "licenciaPendiente": (
                None if justificada else _licencia_que_cubre(pendientes, dia)
            ),
        })

    return {"desde": d.isoformat(), "hasta": h.isoformat(),
            "ausencias": ausencias,
            "ventanaDias": VENTANA_JUSTIFICACION_DIAS}


@router.post("/empleado/{employee_id}/ausencias/{fecha}/justificar",
             dependencies=[GESTIONAR_ASISTENCIA])
def post_justificar(employee_id: int, fecha: str, data: dict = Body(...),
                    usuario: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Adjunta el parte medico, justifica el dia y recalcula el anio."""
    ensure_tablas_asistencia(db)
    ensure_tables(db)
    dia = _fecha(fecha)

    try:
        validar_fecha_justificable(dia, date.today())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    file_name = data.get("fileName")
    mime_type = data.get("mimeType")
    file_data = data.get("fileData")
    if not file_name or not mime_type or not file_data:
        raise HTTPException(
            status_code=400,
            detail="El parte medico es obligatorio: faltan fileName, mimeType o fileData")

    if usuario.get("employeeId") is None:
        raise HTTPException(
            status_code=403,
            detail="Tu usuario no tiene legajo vinculado para registrar la justificacion")

    jornada = db.execute(text("""
        SELECT estado FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha = :fecha
    """), {"emp": employee_id, "fecha": dia}).mappings().first()
    if jornada is None:
        raise HTTPException(status_code=404,
                            detail="No hay una jornada calculada para ese dia")
    # Se acepta justificada para permitir reemplazar el parte por uno
    # corregido. Cualquier otro estado seria borrarle horas reales a la persona.
    if jornada["estado"] not in (ESTADO_AUSENTE, ESTADO_JUSTIFICADA):
        raise HTTPException(
            status_code=400,
            detail=f"El dia esta en estado '{jornada['estado']}' y no es una ausencia")

    documento_id = justificar(
        db, employee_id, dia, file_name, mime_type, file_data,
        data.get("observacion"), int(usuario["employeeId"]),
    )
    recalcular_anio(db, employee_id, dia.year)
    return {"ok": True, "fecha": dia.isoformat(), "documentoId": documento_id}


@router.delete("/empleado/{employee_id}/ausencias/{fecha}/justificar",
               dependencies=[GESTIONAR_ASISTENCIA])
def delete_justificar(employee_id: int, fecha: str,
                      db: Session = Depends(get_db)):
    """Anula la justificacion. El dia vuelve a contar como ausencia."""
    ensure_tablas_asistencia(db)
    ensure_tables(db)
    dia = _fecha(fecha)
    if not borrar_justificacion(db, employee_id, dia):
        raise HTTPException(status_code=404,
                            detail="No hay justificacion para ese dia")
    recalcular_anio(db, employee_id, dia.year)
    return {"eliminado": True, "fecha": dia.isoformat()}
