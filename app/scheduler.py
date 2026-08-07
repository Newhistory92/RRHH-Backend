"""
Job periodico que sincroniza las marcaciones de los relojes.

El estado vive en la tabla RelojSync, no en memoria: un reinicio del backend no
pierde nada, el ciclo siguiente retoma desde ultimaSync.
"""

import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.database.database import SessionLocal
from app.database.jubilacion import (
    aplicar_jubilacion, ensure_columna_jubilacion, fecha_jubilacion_de,
    pendientes_de_jubilar,
)
from app.services.jubilacion import jubilacion_cumplida
from app.services.isapi_client import relojes_configurados
from app.services.reloj_sync import sincronizar_todos
from app.database.asistencia import get_config
from app.services.asistencia_recalc import anios_con_huecos, recalcular_todos

log = logging.getLogger(__name__)

INTERVALO_MINUTOS = 5
HORA_JUBILACIONES = 2  # 2 AM, antes del recalculo de asistencia de las 3
HORA_RECALCULO_ASISTENCIA = 3  # 3 AM, fuera del horario de uso
SEGUNDOS_AUTOREPARACION = 30  # margen para que el arranque termine primero

_scheduler: BackgroundScheduler | None = None


def _tick():
    """Una corrida del sync. Nunca debe propagar excepcion al scheduler."""
    db = SessionLocal()
    try:
        resultados = sincronizar_todos(db)
        for r in resultados:
            if r["error"]:
                log.warning("Sync %s: %s", r["relojIp"], r["error"])
            elif r["insertados"]:
                log.info("Sync %s: %s marcaciones nuevas", r["relojIp"], r["insertados"])
    except Exception as e:
        log.exception("Fallo inesperado en el tick de sincronizacion: %s", e)
    finally:
        db.close()


def _tick_asistencia():
    """
    Recalculo nocturno de todos los anios desde el inicio del modulo.

    Recalcula año por año (no solo el actual) para cubrir marcaciones
    historicas que llegaron tarde al sistema. El costo es proporcional a
    los años de historia; a las 3 AM ese costo es aceptable y la ganancia
    es que cualquier hueco -- en cualquier año -- se repara solo al dia
    siguiente sin intervencion manual.
    """
    db = SessionLocal()
    try:
        cfg = get_config(db)
        inicio = cfg["fechaInicioModulo"]
        inicio = inicio.date() if isinstance(inicio, datetime) else inicio
        anio_inicio = inicio.year
        anio_actual = date.today().year
        total_filas = 0
        total_emp = 0
        for anio in range(anio_inicio, anio_actual + 1):
            resultado = recalcular_todos(db, anio)
            total_emp = resultado["procesados"]
            total_filas += resultado["filas"]
        log.info(
            "Recalculo de asistencia: %s empleados, %s jornadas totales (%s-%s)",
            total_emp, total_filas, anio_inicio, anio_actual,
        )
    except Exception as e:
        log.exception("Fallo inesperado en el recalculo de asistencia: %s", e)
    finally:
        db.close()


def _tick_autoreparacion():
    """
    Busca empleados con jornadas atrasadas y recalcula sus anios.

    Es la red que atrapa el modo de falla que dejo JornadaDiaria vacia: el job
    nocturno corre a las 3 AM y nunca hubo un servidor vivo a esa hora. Corre
    una sola vez, unos segundos despues del arranque, para no demorar el
    startup.
    """
    db = SessionLocal()
    try:
        anios = anios_con_huecos(db)
        if not anios:
            log.info("Autoreparacion de asistencia: sin huecos que completar")
            return
        for anio in anios:
            resultado = recalcular_todos(db, anio, origen="arranque")
            log.info("Autoreparacion %s: %s empleados, %s jornadas, %s errores",
                     anio, resultado["procesados"], resultado["filas"],
                     len(resultado["errores"]))
    except Exception as e:
        log.exception("Fallo inesperado en la autoreparacion de asistencia: %s", e)
    finally:
        db.close()


def _tick_jubilaciones():
    """
    Aplica las jubilaciones cuya fecha ya llego.

    Es la pieza que hace util cargar una fecha futura: RRHH la carga cuando la
    sabe y la persona sigue trabajando hasta ese dia.

    Solo avanza. Nunca reactiva a nadie, ni siquiera si alguien edito la fecha
    hacia adelante: volver a activar es siempre un acto explicito de RRHH desde
    la interfaz.

    Corre antes del recalculo de asistencia para que el rango del dia ya tenga
    la cota superior puesta cuando aquel arranque.
    """
    db = SessionLocal()
    try:
        ensure_columna_jubilacion(db)
        hoy = date.today()
        ids = pendientes_de_jubilar(db, hoy)
        if not ids:
            log.info("Jubilaciones: no hay ninguna para aplicar hoy")
            return
        for eid in ids:
            fecha = fecha_jubilacion_de(db, eid)
            if not fecha or not jubilacion_cumplida(fecha, hoy):
                log.warning(
                    "Jubilaciones: empleado %s no cumple la condicion al re-leer, "
                    "probablemente la fecha fue editada entre queries. Se omite.",
                    eid,
                )
                continue
            aplicar_jubilacion(db, eid, fecha, hoy)
            log.info("Jubilacion aplicada: empleado %s, fecha %s", eid, fecha)
        log.info("Jubilaciones: %s empleados pasaron a Jubilado", len(ids))
    except Exception as e:
        log.exception("Fallo inesperado en el tick de jubilaciones: %s", e)
    finally:
        db.close()


def iniciar_scheduler():
    """
    Arranca el scheduler. Los jobs de asistencia y jubilacion arrancan siempre;
    el sync de relojes solo arranca si RELOJ_IPS esta configurado.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")

    # ── Jobs de asistencia y jubilacion: siempre activos ───────────────────
    _scheduler.add_job(
        _tick_jubilaciones,
        "cron",
        hour=HORA_JUBILACIONES,
        minute=0,
        id="jubilaciones",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    _scheduler.add_job(
        _tick_asistencia,
        "cron",
        hour=HORA_RECALCULO_ASISTENCIA,
        minute=0,
        id="recalculo_asistencia",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    _scheduler.add_job(
        _tick_autoreparacion,
        "date",
        run_date=datetime.now() + timedelta(seconds=SEGUNDOS_AUTOREPARACION),
        id="autoreparacion_asistencia",
        max_instances=1,
        replace_existing=True,
    )

    # ── Sync de relojes: solo si hay relojes configurados ──────────────────
    if relojes_configurados():
        _scheduler.add_job(
            _tick,
            "interval",
            minutes=INTERVALO_MINUTOS,
            id="sync_relojes",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        log.info("Sync de relojes activo: cada %s min", INTERVALO_MINUTOS)
    else:
        log.warning("RELOJ_IPS vacio: el sync de relojes no se inicia")

    _scheduler.start()
    log.info(
        "Scheduler iniciado: jubilaciones a las %s:00, "
        "recalculo historia a las %s:00, autoreparacion en %s s",
        HORA_JUBILACIONES, HORA_RECALCULO_ASISTENCIA, SEGUNDOS_AUTOREPARACION,
    )
    return _scheduler


def detener_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
