"""
Carga inicial de horas de permiso ya consumidas.

Transitorio: existe para la migracion. Cuando termine, se le quita el permiso
al rol y los dos endpoints quedan inalcanzables sin tocar codigo.
"""

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import require_permission
from app.database.consumo_inicial_permisos import (
    carga_de_empleado, ensure_table, upsert_consumo,
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
    Lo cargado para el anio en curso, con el cupo como contexto.

    horasConsumidas null significa "no se cargo nada" y 0 significa "se
    determino que no uso ninguna". Son estados distintos y el panel los
    muestra distinto.
    """
    ensure_table(db)
    anio = date.today().year
    fila = carga_de_empleado(db, employee_id, anio)
    cargado_en = fila["cargadoEn"] if fila else None
    return {
        "anio": anio,
        "cupoAnual": _cupo_de_empleado(db, employee_id),
        "horasConsumidas": float(fila["horasConsumidas"]) if fila else None,
        "cargadoPor": fila["cargadoPor"] if fila else None,
        "cargadoEn": cargado_en.isoformat() if cargado_en else None,
    }


@router.put("/{employee_id}")
def put_carga_inicial_permisos(employee_id: int, data: dict = Body(...),
                               user: dict = PERMISO,
                               db: Session = Depends(get_db)):
    """
    Guarda las horas del anio en curso y recalcula ese anio del empleado.

    El anio no se recibe por parametro: siempre es el calendario en curso, que
    es el unico cargable. Aceptarlo del cliente abriria la puerta a escribir
    anios que despues nadie recalcula.

    El recalculo va sincrono porque es un solo empleado, a diferencia del
    cambio de cupo de una jornada, que toca a toda su nomina y por eso va en
    segundo plano.
    """
    ensure_table(db)
    horas = _validar_horas(data.get("horasConsumidas"))
    anio = date.today().year
    upsert_consumo(db, employee_id, anio, horas, user.get("employeeId"))
    recalcular_anio(db, employee_id, anio)
    return {"ok": True, "anio": anio, "horasConsumidas": horas}
