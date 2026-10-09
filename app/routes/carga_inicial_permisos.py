"""
Carga inicial de horas de permiso ya consumidas.

Transitorio: existe para la migracion. Cuando termine, se le quita el permiso
al rol y los tres endpoints quedan inalcanzables sin tocar codigo.
"""

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import require_permission
from app.database.consumo_inicial_permisos import (
    agregar_asiento, asientos_de_empleado, borrar_asiento, ensure_table,
    total_de_empleado,
)
from app.database.database import SessionLocal
from app.services.asistencia_recalc import recalcular_anio

router = APIRouter(prefix="/asistencia/carga-inicial-permisos",
                   tags=["Carga inicial permisos"])

# Mismo atajo contra el error de tipeo que usa el cupo de la jornada: 2000 h es
# mas que un anio laboral completo. No hay tope contra el cupo del empleado a
# proposito: alguien pudo haber usado mas horas de las que su cupo cubre, y eso
# tiene que poder cargarse.
HORAS_MAX = 2000.0

PERMISO = Depends(require_permission("asistencia.cargaInicialPermisos"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _validar_horas(valor) -> float:
    """Normaliza horasConsumidas a float, o 400 si no tiene sentido."""
    try:
        horas = float(valor)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="horasConsumidas debe ser un numero")
    if horas < 0:
        raise HTTPException(status_code=400,
                            detail="horasConsumidas no puede ser negativo")
    if horas > HORAS_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"horasConsumidas no puede superar {int(HORAS_MAX)} horas")
    return horas


def _cupo_de_empleado(db: Session, employee_id: int) -> float:
    """El cupo de la jornada del empleado, 0 si no tiene jornada asignada."""
    fila = db.execute(text("""
        SELECT j.horasPermisoAnual AS cupo
        FROM Employee e
        LEFT JOIN JornadaLaboral j ON e.jornadaId = j.id
        WHERE e.id = :emp
    """), {"emp": employee_id}).mappings().first()
    return float(fila["cupo"] or 0) if fila else 0.0


@router.get("/{employee_id}")
def get_carga_inicial_permisos(employee_id: int, _user: dict = PERMISO,
                               db: Session = Depends(get_db)):
    """
    Los asientos del anio en curso y su total, con el cupo como contexto.

    total null significa "no hay ningun asiento" y 0 significa "los asientos
    suman cero". Son estados distintos y el panel los muestra distinto.
    """
    ensure_table(db)
    anio = date.today().year
    asientos = asientos_de_empleado(db, employee_id, anio)
    return {
        "anio": anio,
        "cupoAnual": _cupo_de_empleado(db, employee_id),
        "total": total_de_empleado(db, employee_id, anio),
        "asientos": [{
            "id": int(a["id"]),
            "horasConsumidas": float(a["horasConsumidas"]),
            "cargadoPor": a["cargadoPor"],
            "cargadoEn": a["cargadoEn"].isoformat() if a["cargadoEn"] else None,
        } for a in asientos],
    }


@router.post("/{employee_id}")
def post_carga_inicial_permisos(employee_id: int, data: dict = Body(...),
                                user: dict = PERMISO,
                                db: Session = Depends(get_db)):
    """
    Agrega un asiento al anio en curso y recalcula ese anio del empleado.

    Es POST y no PUT porque no se guarda "el valor": se agrega una carga. Dos
    cargas del mismo anio se suman, que es el comportamiento buscado.

    El anio no se recibe por parametro: siempre es el calendario en curso, que
    es el unico cargable. Aceptarlo del cliente abriria la puerta a escribir
    anios que despues nadie recalcula.

    El recalculo va sincrono porque es un solo empleado, a diferencia del
    cambio de cupo de una jornada, que toca a toda su nomina y va en segundo
    plano.
    """
    ensure_table(db)
    horas = _validar_horas(data.get("horasConsumidas"))
    anio = date.today().year
    agregar_asiento(db, employee_id, anio, horas, user.get("employeeId"))
    recalcular_anio(db, employee_id, anio)
    return {"ok": True, "anio": anio, "horasConsumidas": horas}


@router.delete("/{employee_id}/{asiento_id}")
def delete_carga_inicial_permisos(employee_id: int, asiento_id: int,
                                  _user: dict = PERMISO,
                                  db: Session = Depends(get_db)):
    """
    Borra un asiento y recalcula. Es la unica forma de corregir una carga
    equivocada: los asientos no se editan en el lugar.

    404 cuando el asiento no existe o no es de ese empleado -borrar_asiento
    filtra por employeeId, asi que el id de la URL no alcanza para borrarle
    uno a otra persona. Sin cambio no se recalcula nada.
    """
    ensure_table(db)
    if not borrar_asiento(db, employee_id, asiento_id):
        raise HTTPException(status_code=404,
                            detail="El asiento no existe o no es de este agente")
    anio = date.today().year
    recalcular_anio(db, employee_id, anio)
    return {"ok": True, "anio": anio}
