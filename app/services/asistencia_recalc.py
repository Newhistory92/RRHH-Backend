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

from app.database.asistencia import get_config, reemplazar_jornadas, saldo_acumulado
from app.database.asistencia_auditoria import (
    abrir_recalculo, cerrar_recalculo, correcciones_por_dia,
)
from app.services.asistencia_calc import (
    EntradaDia, Permiso, ResultadoDia, Tolerancias, calcular_anio,
)
from app.services.marcaciones_norm import Correccion, HorarioDia, normalizar

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
        LEFT JOIN (
            SELECT employeeId, MIN(fechaIngreso) AS fechaIngreso
            FROM CondicionLaboral
            GROUP BY employeeId
        ) c ON c.employeeId = e.id
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


def _a_fila(r: ResultadoDia) -> dict:
    """
    La fila de JornadaDiaria. Todo sale del resultado: los flags manuales ya
    vienen resueltos desde los extremos, y corregidoPor y observacion viven en
    JornadaCorreccion, no aca.
    """
    return {
        "fecha": r.fecha,
        "estado": r.estado,
        "horasRequeridas": round(r.horasRequeridas, 2),
        "horasTrabajadas": round(r.horasTrabajadas, 2),
        "saldoDia": round(r.saldoDia, 2),
        "entrada": r.entrada,
        "salida": r.salida,
        "entradaManual": r.entradaManual,
        "salidaManual": r.salidaManual,
        "permisoBanco": round(r.permisoBanco, 2),
        "permisoDeuda": round(r.permisoDeuda, 2),
        "permisoOficial": round(r.permisoOficial, 2),
        "toleranciaEntradaUsada": r.toleranciaEntradaUsada,
        "toleranciaSalidaUsada": r.toleranciaSalidaUsada,
        "abusoEntrada": r.abusoEntrada,
        "abusoSalida": r.abusoSalida,
    }


def _a_incidencias(resultados: list[ResultadoDia]) -> list[dict]:
    """Aplana las incidencias de todos los dias a filas de JornadaIncidencia."""
    return [
        {"fecha": r.fecha, "tipo": tipo, "detalle": None}
        for r in resultados
        for tipo in r.incidencias
    ]


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
        # isinstance(datetime_obj, date) es True porque datetime hereda de date;
        # hay que verificar el tipo mas especifico primero.
        ingreso = ingreso.date() if isinstance(ingreso, datetime) else ingreso
        desde = max(desde, ingreso)
    hasta = min(date(anio, 12, 31), date.today())
    if desde > hasta:
        return 0

    correcciones = correcciones_por_dia(db, employee_id, desde, hasta)
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
        entradas.append(EntradaDia(
            fecha=d,
            extremos=normalizar(
                marcaciones.get(d, []), horario, correcciones.get(d),
            ),
            horario=horario,
            es_feriado=d in feriados,
            tiene_licencia=d in licencias,
            permisos=permisos.get(d, []),
        ))

    resultados = calcular_anio(entradas, Tolerancias(
        entradaMin=cfg["toleranciaEntradaMin"],
        salidaMin=cfg["toleranciaSalidaMin"],
        estrictaEntradaMin=cfg["toleranciaEstrictaEntradaMin"],
        estrictaSalidaMin=cfg["toleranciaEstrictaSalidaMin"],
    ))
    filas_count = reemplazar_jornadas(
        db, employee_id, desde, hasta,
        [_a_fila(r) for r in resultados], _a_incidencias(resultados),
    )
    # Sincroniza Employee.horas con el saldo acumulado real para que el
    # modal de estadisticas muestre el valor correcto sin consulta extra.
    nuevo_saldo = saldo_acumulado(db, employee_id)
    db.execute(text(
        "UPDATE Employee SET horas = :s WHERE id = :id"
    ), {"s": round(nuevo_saldo, 2), "id": employee_id})
    db.commit()
    return filas_count


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


def recalcular_todos(db: Session, anio: int, origen: str = "nocturno",
                     disparado_por: Optional[int] = None) -> dict:
    """
    Recalculo masivo. Un empleado que falla no debe abortar el resto: se
    registra y se sigue. Toda la corrida queda auditada en RecalculoLog.
    """
    log_id = abrir_recalculo(db, origen, disparado_por, None,
                             date(anio, 1, 1), date(anio, 12, 31))
    ids = [r["id"] for r in db.execute(text(
        "SELECT id FROM Employee WHERE biometricoId IS NOT NULL ORDER BY id"
    )).mappings().all()]

    filas = 0
    ok = 0
    errores = []
    for eid in ids:
        try:
            filas += recalcular_anio(db, eid, anio)
            ok += 1
        except Exception as e:
            db.rollback()
            log.warning("Recalculo fallido para empleado %s: %s", eid, e)
            errores.append({"employeeId": eid, "error": str(e)})

    cerrar_recalculo(db, log_id, ok, filas, errores)
    return {"procesados": ok, "filas": filas, "errores": errores}


def anios_con_huecos(db: Session, hoy: Optional[date] = None) -> list[int]:
    """
    Anios que hay que recalcular porque algun empleado vinculado quedo atrasado.

    Toma la fecha calculada mas vieja entre todos los empleados con reloj: si
    alguno no tiene ninguna jornada, cuenta como fechaInicioModulo. Si esa
    fecha esta a mas de un dia de hoy, hay hueco.

    Es deliberadamente grueso. Recalcular un anio de mas cuesta segundos y da
    el mismo resultado, mientras que no detectar un hueco deja el saldo mal.
    """
    cfg = get_config(db)
    inicio = cfg["fechaInicioModulo"]
    if not isinstance(inicio, date):
        inicio = inicio.date()
    hoy = hoy or date.today()

    fila = db.execute(text("""
        SELECT MIN(COALESCE(j.ultima, :inicio)) AS mas_atrasada
        FROM Employee e
        LEFT JOIN (
            SELECT employeeId, MAX(fecha) AS ultima
            FROM JornadaDiaria GROUP BY employeeId
        ) j ON j.employeeId = e.id
        WHERE e.biometricoId IS NOT NULL
    """), {"inicio": inicio}).mappings().first()

    if fila is None or fila["mas_atrasada"] is None:
        return []
    atrasada = fila["mas_atrasada"]
    if not isinstance(atrasada, date):
        atrasada = atrasada.date()
    if atrasada >= hoy - timedelta(days=1):
        return []
    return list(range(max(atrasada.year, inicio.year), hoy.year + 1))
