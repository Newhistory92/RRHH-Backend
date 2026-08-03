"""
Job periodico que sincroniza las marcaciones de los relojes.

El estado vive en la tabla RelojSync, no en memoria: un reinicio del backend no
pierde nada, el ciclo siguiente retoma desde ultimaSync.
"""

import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.database.database import SessionLocal
from app.services.isapi_client import relojes_configurados
from app.services.reloj_sync import sincronizar_todos
from app.services.asistencia_recalc import anios_con_huecos, recalcular_todos

log = logging.getLogger(__name__)

INTERVALO_MINUTOS = 5
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
    Recalculo nocturno del anio en curso. Recomputa todo el anio en lugar de
    solo ayer: cuesta unos minutos a las 3 AM y a cambio se auto-repara,
    corrigiendo cualquier inconsistencia que haya dejado un disparador fallido.
    """
    db = SessionLocal()
    try:
        resultado = recalcular_todos(db, date.today().year)
        log.info("Recalculo de asistencia: %s empleados, %s jornadas",
                 resultado["procesados"], resultado["filas"])
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


def iniciar_scheduler():
    """Arranca el job. Si no hay relojes configurados, no arranca nada."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    if not relojes_configurados():
        log.warning("RELOJ_IPS vacio: el sync de relojes no se inicia")
        return None

    _scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")
    _scheduler.add_job(
        _tick,
        "interval",
        minutes=INTERVALO_MINUTOS,
        id="sync_relojes",
        max_instances=1,       # nunca dos corridas simultaneas
        coalesce=True,         # si se acumularon ticks, corre uno solo
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
    _scheduler.start()
    log.info("Scheduler iniciado: sync cada %s min, recalculo a las %s:00, "
             "autoreparacion en %s s",
             INTERVALO_MINUTOS, HORA_RECALCULO_ASISTENCIA, SEGUNDOS_AUTOREPARACION)
    return _scheduler


def detener_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
