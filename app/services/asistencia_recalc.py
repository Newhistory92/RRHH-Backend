"""
Orquestacion del recalculo: carga los insumos en bloque, delega el calculo al
motor puro y reemplaza las filas del rango.

La unidad de recalculo es (empleado, anio) y siempre se recomputa desde el 1 de
enero, porque el banco de permisos se consume en orden cronologico. Hay un solo
camino de codigo: no existe una variante incremental que pueda desviarse del
calculo completo.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.asistencia import get_config, reemplazar_jornadas
from app.services.asistencia_calc import (
    EntradaDia, HorarioDia, Permiso, ResultadoDia, calcular_anio,
)

log = logging.getLogger(__name__)


def _rango_dias(desde: date, hasta: date):
    d = desde
    while d <= hasta:
        yield d
        d += timedelta(days=1)


def _datos_empleado(db: Session, employee_id: int) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT e.id, e.biometricoId,
               h.horaInicio, h.horaFin, h.horasTrabajo,
               c.fechaIngreso
        FROM Employee e
        LEFT JOIN Horario h ON e.cronogramaId = h.id
        LEFT JOIN CondicionLaboral c ON c.employeeId = e.id
        WHERE e.id = :id
    """), {"id": employee_id}).mappings().first()
    return dict(fila) if fila else None


def _marcaciones_por_dia(db: Session, biometrico_id: str,
                         desde: date, hasta: date) -> dict[date, list[datetime]]:
    filas = db.execute(text("""
        SELECT fechaHora FROM Marcacion
        WHERE biometricoId = :bio AND fechaHora >= :desde AND fechaHora < :hasta
        ORDER BY fechaHora
    """), {"bio": str(biometrico_id), "desde": datetime.combine(desde, datetime.min.time()),
           "hasta": datetime.combine(hasta + timedelta(days=1), datetime.min.time())}
    ).mappings().all()
    por_dia: dict[date, list[datetime]] = {}
    for f in filas:
        por_dia.setdefault(f["fechaHora"].date(), []).append(f["fechaHora"])
    return por_dia


def _feriados(db: Session, desde: date, hasta: date) -> set[date]:
    filas = db.execute(text("""
        SELECT fecha FROM Feriado
        WHERE activo = 1 AND fecha >= :desde AND fecha <= :hasta
    """), {"desde": desde, "hasta": hasta}).mappings().all()
    return {f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
            for f in filas}


def _dias_con_licencia(db: Session, employee_id: int,
                       desde: date, hasta: date) -> set[date]:
    filas = db.execute(text("""
        SELECT startDate, endDate FROM License
        WHERE employeeId = :emp AND status = 'Aprobada'
          AND startDate <= :hasta AND endDate >= :desde
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    dias: set[date] = set()
    for f in filas:
        ini = f["startDate"] if isinstance(f["startDate"], date) else f["startDate"].date()
        fin = f["endDate"] if isinstance(f["endDate"], date) else f["endDate"].date()
        for d in _rango_dias(max(ini, desde), min(fin, hasta)):
            dias.add(d)
    return dias


def _permisos_por_dia(db: Session, employee_id: int,
                      desde: date, hasta: date) -> dict[date, list[Permiso]]:
    filas = db.execute(text("""
        SELECT date, hours, oficial FROM Permission
        WHERE employeeId = :emp AND date >= :desde AND date <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    por_dia: dict[date, list[Permiso]] = {}
    for f in filas:
        d = f["date"] if isinstance(f["date"], date) else f["date"].date()
        por_dia.setdefault(d, []).append(
            Permiso(horas=float(f["hours"] or 0), oficial=bool(f["oficial"]))
        )
    return por_dia


def _correcciones_por_dia(db: Session, employee_id: int, desde: date,
                          hasta: date) -> dict[date, dict]:
    """
    Las cargas manuales de RRHH sobreviven al recalculo: se releen de la propia
    JornadaDiaria antes de borrar el rango y se reinyectan al motor.
    """
    filas = db.execute(text("""
        SELECT fecha, entrada, salida, entradaManual, salidaManual,
               corregidoPor, corregidoAt, observacion
        FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
          AND (entradaManual = 1 OR salidaManual = 1)
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    out: dict[date, dict] = {}
    for f in filas:
        d = f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
        out[d] = dict(f)
    return out


def _a_fila(r: ResultadoDia, correccion: Optional[dict]) -> dict:
    c = correccion or {}
    return {
        "fecha": r.fecha,
        "estado": r.estado,
        "horasRequeridas": round(r.horasRequeridas, 2),
        "horasTrabajadas": round(r.horasTrabajadas, 2),
        "saldoDia": round(r.saldoDia, 2),
        "entrada": r.entrada,
        "salida": r.salida,
        "entradaManual": bool(c.get("entradaManual", False)),
        "salidaManual": bool(c.get("salidaManual", False)),
        "permisoBanco": round(r.permisoBanco, 2),
        "permisoDeuda": round(r.permisoDeuda, 2),
        "permisoOficial": round(r.permisoOficial, 2),
        "corregidoPor": c.get("corregidoPor"),
        "corregidoAt": c.get("corregidoAt"),
        "observacion": c.get("observacion"),
    }


def recalcular_anio(db: Session, employee_id: int, anio: int) -> int:
    """Recomputa el anio completo de un empleado. Idempotente."""
    emp = _datos_empleado(db, employee_id)
    if emp is None or not emp["biometricoId"]:
        return 0

    cfg = get_config(db)
    inicio_modulo = cfg["fechaInicioModulo"]
    if not isinstance(inicio_modulo, date):
        inicio_modulo = inicio_modulo.date()

    desde = max(date(anio, 1, 1), inicio_modulo)
    ingreso = emp.get("fechaIngreso")
    if ingreso is not None:
        ingreso = ingreso if isinstance(ingreso, date) else ingreso.date()
        desde = max(desde, ingreso)
    hasta = min(date(anio, 12, 31), date.today())
    if desde > hasta:
        return 0

    correcciones = _correcciones_por_dia(db, employee_id, desde, hasta)
    marcaciones = _marcaciones_por_dia(db, emp["biometricoId"], desde, hasta)
    feriados = _feriados(db, desde, hasta)
    licencias = _dias_con_licencia(db, employee_id, desde, hasta)
    permisos = _permisos_por_dia(db, employee_id, desde, hasta)

    horario = None
    if emp["horaInicio"] is not None and emp["horaFin"] is not None:
        horario = HorarioDia(
            horaInicio=float(emp["horaInicio"]),
            horaFin=float(emp["horaFin"]),
            horasTrabajo=float(emp["horasTrabajo"] or 0),
        )

    entradas = []
    for d in _rango_dias(desde, hasta):
        c = correcciones.get(d, {})
        entradas.append(EntradaDia(
            fecha=d,
            marcaciones=marcaciones.get(d, []),
            horario=horario,
            es_feriado=d in feriados,
            tiene_licencia=d in licencias,
            permisos=permisos.get(d, []),
            entrada_manual=c.get("entrada") if c.get("entradaManual") else None,
            salida_manual=c.get("salida") if c.get("salidaManual") else None,
        ))

    resultados = calcular_anio(
        entradas, cfg["toleranciaEntradaMin"], cfg["toleranciaSalidaMin"],
    )
    filas = [_a_fila(r, correcciones.get(r.fecha)) for r in resultados]
    return reemplazar_jornadas(db, employee_id, desde, hasta, filas)


def recalcular_historia(db: Session, employee_id: int) -> int:
    """
    Recomputa todos los anios desde el arranque del modulo. Es lo que se dispara
    al asignar un biometricoId: las marcaciones huerfanas que ya estaban
    guardadas aparecen retroactivamente sin resincronizar los relojes.
    """
    cfg = get_config(db)
    inicio = cfg["fechaInicioModulo"]
    if not isinstance(inicio, date):
        inicio = inicio.date()
    total = 0
    for anio in range(inicio.year, date.today().year + 1):
        total += recalcular_anio(db, employee_id, anio)
    return total


def recalcular_todos(db: Session, anio: int) -> dict:
    """
    Recalculo masivo del job nocturno. Un empleado que falla no debe abortar el
    resto: se registra y se sigue.
    """
    ids = [r["id"] for r in db.execute(text(
        "SELECT id FROM Employee WHERE biometricoId IS NOT NULL ORDER BY id"
    )).mappings().all()]

    filas = 0
    ok = 0
    for eid in ids:
        try:
            filas += recalcular_anio(db, eid, anio)
            ok += 1
        except Exception as e:
            db.rollback()
            log.warning("Recalculo fallido para empleado %s: %s", eid, e)
    return {"empleados": ok, "filas": filas}
