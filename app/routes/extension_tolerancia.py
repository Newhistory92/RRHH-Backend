"""
Extensiones de tolerancia por dia.

RRHH otorga, para una fecha puntual, una tolerancia distinta de los 15
minutos de siempre. Aplica solo a quien tiene Employee.fueraAnilloCircunvalacion:
el resto mantiene los 15 haya o no extension cargada.
"""

import logging
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth_middleware import require_permission
from app.database.asistencia import get_config
from app.database.database import SessionLocal
from app.database.extension_tolerancia import (
    agregar, borrar, ensure_table, existe_para_fecha, listar,
)
from app.services.asistencia_recalc import recalcular_marcados_fuera_del_anillo
from app.services.bajas import a_date

log = logging.getLogger(__name__)

router = APIRouter(prefix="/asistencia/extensiones-tolerancia",
                   tags=["Extension de tolerancia"])

# 8 horas ya es una jornada entera y vacia el concepto de tolerancia: mas que
# eso solo puede ser un dedazo.
MINUTOS_MAX = 480

PERMISO = Depends(require_permission("asistencia.gestionar"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _validar_fecha(valor) -> date:
    """
    Normaliza la fecha y exige que sea de hoy en adelante.

    Se valida en el servidor y no solo con el min del input: el min se saltea
    desde DevTools, y una extension retroactiva reescribiria asistencia que ya
    se liquido.
    """
    try:
        fecha = date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="fecha debe venir como YYYY-MM-DD")
    if fecha < date.today():
        raise HTTPException(
            status_code=400,
            detail="No se puede extender la tolerancia de un dia que ya paso")
    return fecha


def _validar_minutos(valor, base: int, extremo: str) -> int:
    """
    Normaliza los minutos y exige que superen la tolerancia vigente.

    Un valor menor RECORTARIA el margen de los que viven lejos, exactamente
    al reves de lo que el boton promete. Vale igual para la salida: que el
    campo sea opcional no lo exime.
    """
    try:
        minutos = int(valor)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"La tolerancia de {extremo} debe ser un numero de minutos")
    if minutos <= base:
        raise HTTPException(
            status_code=400,
            detail=(f"La tolerancia de {extremo} tiene que superar los {base} "
                    f"minutos vigentes: {minutos} no es una extension"))
    if minutos > MINUTOS_MAX:
        raise HTTPException(
            status_code=400,
            detail=(f"La tolerancia de {extremo} no puede superar "
                    f"{MINUTOS_MAX} minutos"))
    return minutos


def _recalcular_si_hace_falta(db: Session, fecha: date) -> None:
    """
    Recalcula solo si el dia ya esta calculado.

    El motor computa hasta hoy nada mas, asi que un dia futuro todavia no
    existe en JornadaDiaria: va a nacer con la extension puesta cuando llegue,
    sin que nadie tenga que rehacer nada.

    Si el recalculo falla, la extension ya quedo escrita: se registra y el job
    nocturno la aplica. Un 500 aca haria creer que no se guardo cuando si se
    guardo.
    """
    if fecha > date.today():
        return
    try:
        recalcular_marcados_fuera_del_anillo(db, fecha.year)
    except Exception as e:
        log.warning("Recalculo por extension de tolerancia del %s fallido: %s",
                    fecha, e)


@router.get("")
def get_extensiones(_user: dict = PERMISO, db: Session = Depends(get_db)):
    """Todas las extensiones cargadas, la mas nueva primero."""
    ensure_table(db)
    return {
        "extensiones": [{
            "id": int(e["id"]),
            "fecha": a_date(e["fecha"]).isoformat(),
            "toleranciaEntradaMin": int(e["toleranciaEntradaMin"]),
            "toleranciaSalidaMin": (None if e["toleranciaSalidaMin"] is None
                                    else int(e["toleranciaSalidaMin"])),
            "cargadoPor": e["cargadoPor"],
            "cargadoEn": e["cargadoEn"].isoformat() if e["cargadoEn"] else None,
        } for e in listar(db)],
    }


@router.post("")
def post_extension(data: dict = Body(...), user: dict = PERMISO,
                   db: Session = Depends(get_db)):
    """
    Da de alta la extension de un dia.

    Una por fecha: un segundo alta para el mismo dia responde 409 pidiendo
    borrar la que esta, en vez de pisar en silencio un valor que le perdona
    horas a toda la planta que vive lejos.
    """
    ensure_table(db)
    cfg = get_config(db)
    fecha = _validar_fecha(data.get("fecha"))
    entrada = _validar_minutos(data.get("toleranciaEntradaMin"),
                               base=cfg["toleranciaEntradaMin"],
                               extremo="entrada")
    salida_cruda = data.get("toleranciaSalidaMin")
    salida = (None if salida_cruda in (None, "")
              else _validar_minutos(salida_cruda,
                                    base=cfg["toleranciaSalidaMin"],
                                    extremo="salida"))

    if existe_para_fecha(db, fecha):
        raise HTTPException(
            status_code=409,
            detail=("Ya hay una extension cargada para esa fecha. "
                    "Borrala primero si queres cambiarla."))

    agregar(db, fecha, entrada, salida, user.get("employeeId"))
    _recalcular_si_hace_falta(db, fecha)
    return {"ok": True, "fecha": fecha.isoformat()}


@router.delete("/{extension_id}")
def delete_extension(extension_id: int, _user: dict = PERMISO,
                     db: Session = Depends(get_db)):
    """
    Borra una extension y recalcula el anio de SU fecha, no el actual: una
    extension de diciembre borrada ya entrado enero pertenece a diciembre.
    """
    ensure_table(db)
    fecha = borrar(db, extension_id)
    if fecha is None:
        raise HTTPException(status_code=404, detail="La extension no existe")
    _recalcular_si_hace_falta(db, fecha)
    return {"ok": True, "fecha": fecha.isoformat()}
