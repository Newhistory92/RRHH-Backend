"""
Sincronizacion de marcaciones desde los relojes hacia SQL Server.

AcsEvent filtra por startTime/endTime y no admite "serialNo mayor a", asi que
el sync no usa un cursor de correlativo sino una ventana temporal con solape.
El solape cubre desfasajes de hora y eventos registrados con retraso; los
duplicados que genera los descarta la unicidad (relojIp, serialNo), lo que hace
que reprocesar una ventana sea inofensivo.
"""

import logging
from datetime import datetime, time, timedelta
from typing import Iterator, Optional

from sqlalchemy.orm import Session

from app.database.marcaciones import (
    ensure_tables, registrar_reloj, ultima_sync, marcar_sync_ok,
    marcar_sync_error, max_serial_no, insertar_marcaciones,
)
from app.services.isapi_client import (
    ISAPIError, buscar_eventos, relojes_configurados,
)

log = logging.getLogger(__name__)

SOLAPE_MINUTOS = 10
DIAS_CARGA_INICIAL = 30
MAX_RESULTS = 100
MAX_PAGINAS = 500  # tope de seguridad: 50.000 marcaciones por corrida

MAJOR_ACCESO = 5
MINOR_MARCACION_VALIDA = 38


def calcular_ventana(ultima: Optional[datetime], ahora: datetime,
                     dias_iniciales: int = DIAS_CARGA_INICIAL) -> tuple[datetime, datetime]:
    """Sin sync previa trae el ultimo mes; con sync previa, desde ahi menos el solape."""
    if ultima is None:
        return ahora - timedelta(days=dias_iniciales), ahora
    return ultima - timedelta(minutes=SOLAPE_MINUTOS), ahora


def ventanas_diarias(desde: datetime,
                     hasta: datetime) -> Iterator[tuple[datetime, datetime]]:
    """
    Parte un rango en ventanas que no cruzan la medianoche.

    La carga inicial pedia 30 dias en una sola llamada y los equipos devolvian
    solo una fraccion: en el periodo 30/06-29/07 se capturo el 7,4% del rango
    de correlativos, contra el 25% del sync incremental. Pedir de a un dia
    mantiene cada respuesta dentro de lo que el equipo puede entregar.

    Una ventana corta -los 5 minutos del sync incremental- sale entera, sin
    partir.
    """
    actual = desde
    while actual < hasta:
        siguiente_medianoche = datetime.combine(
            actual.date() + timedelta(days=1), time.min,
        )
        fin = min(siguiente_medianoche, hasta)
        yield actual, fin
        actual = fin


def parece_truncado(payload: dict) -> bool:
    """
    El equipo devolvio exactamente el tope pedido y dijo que no hay mas.

    Es el sintoma de un dispositivo que corta la respuesta por su cuenta en vez
    de paginar: si de verdad no hubiera mas eventos, el numero seria menor al
    tope casi siempre.
    """
    ev = (payload or {}).get("AcsEvent") or {}
    if ev.get("responseStatusStrg") == "MORE":
        return False
    return ev.get("numOfMatches") == MAX_RESULTS


def _parsear_fecha(crudo: str) -> Optional[datetime]:
    """
    '2026-07-28T06:08:29-03:00' -> datetime(2026,7,28,6,8,29) naive.
    Se conserva la hora de pared local: el motor de asistencia la compara
    contra Horario.horaInicio, que tambien es hora local.
    """
    try:
        return datetime.fromisoformat(crudo).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def extraer_marcaciones(payload: dict, reloj_ip: str) -> list[dict]:
    """Filtra el payload a marcaciones validas y lo normaliza a filas de Marcacion."""
    eventos = ((payload or {}).get("AcsEvent") or {}).get("InfoList") or []
    filas = []
    for ev in eventos:
        if ev.get("major") != MAJOR_ACCESO:
            continue
        if ev.get("minor") != MINOR_MARCACION_VALIDA:
            continue
        bio = str(ev.get("employeeNoString") or "").strip()
        if not bio:
            continue
        fecha = _parsear_fecha(ev.get("time"))
        if fecha is None:
            continue
        serial = ev.get("serialNo")
        if serial is None:
            continue
        filas.append({
            "relojIp": reloj_ip,
            "serialNo": int(serial),
            "biometricoId": bio,
            "nombreReloj": (ev.get("name") or None),
            "fechaHora": fecha,
            "verifyMode": (ev.get("currentVerifyMode") or None),
        })
    return filas


def hay_mas_paginas(payload: dict) -> bool:
    estado = ((payload or {}).get("AcsEvent") or {}).get("responseStatusStrg")
    return estado == "MORE"


def _sincronizar_ventana(db: Session, reloj_ip: str, desde: datetime,
                         hasta: datetime, resultado: dict) -> int:
    """
    Una ventana temporal, paginada hasta agotarla. Acumula en resultado y
    devuelve el serialNo mas alto que vio.
    """
    posicion = 0
    max_visto = 0
    for _ in range(MAX_PAGINAS):
        payload = buscar_eventos(reloj_ip, desde, hasta, posicion, MAX_RESULTS)
        filas = extraer_marcaciones(payload, reloj_ip)
        resultado["leidos"] += len(filas)
        if filas:
            resultado["insertados"] += insertar_marcaciones(db, filas)
            max_visto = max(max_visto, max(f["serialNo"] for f in filas))
        if not hay_mas_paginas(payload):
            if parece_truncado(payload):
                log.warning(
                    "Reloj %s: la ventana %s a %s devolvio el tope exacto de "
                    "%s resultados sin indicar mas paginas. El equipo pudo "
                    "haber cortado la respuesta.",
                    reloj_ip, desde, hasta, MAX_RESULTS,
                )
                resultado["ventanasTruncadas"].append(
                    f"{desde.isoformat()}/{hasta.isoformat()}"
                )
            return max_visto
        posicion += (payload.get("AcsEvent") or {}).get("numOfMatches", MAX_RESULTS)

    log.warning(
        "Reloj %s: cap MAX_PAGINAS=%s alcanzado en la ventana %s a %s. "
        "Quedan eventos sin leer.",
        reloj_ip, MAX_PAGINAS, desde, hasta,
    )
    resultado["ventanasTruncadas"].append(
        f"{desde.isoformat()}/{hasta.isoformat()}"
    )
    return max_visto


def sincronizar_reloj(db: Session, reloj_ip: str,
                     desde: Optional[datetime] = None,
                     hasta: Optional[datetime] = None) -> dict:
    """
    Sincroniza un equipo iterando ventanas de un dia. Nunca propaga excepcion:
    un reloj caido se registra en RelojSync.ultimoError y no debe tumbar el job
    ni el otro equipo.
    """
    registrar_reloj(db, reloj_ip)
    ahora = hasta or datetime.now()
    if desde is None:
        desde, ahora = calcular_ventana(ultima_sync(db, reloj_ip), ahora)

    resultado = {"relojIp": reloj_ip, "leidos": 0, "insertados": 0,
                 "error": None, "ventanasTruncadas": []}
    previo_max = max_serial_no(db, reloj_ip)

    try:
        max_visto = 0
        for v_desde, v_hasta in ventanas_diarias(desde, ahora):
            max_visto = max(
                max_visto,
                _sincronizar_ventana(db, reloj_ip, v_desde, v_hasta, resultado),
            )

        # Riesgo conocido: si el equipo reinicia su correlativo, los eventos
        # nuevos colisionarian con los viejos y se descartarian en silencio.
        if previo_max is not None and max_visto and max_visto < previo_max:
            log.warning(
                "Reloj %s: serialNo maximo recibido (%s) es menor al almacenado (%s). "
                "Posible reinicio del correlativo: las marcaciones nuevas podrian "
                "estar descartandose por la unicidad.",
                reloj_ip, max_visto, previo_max,
            )

        if resultado["ventanasTruncadas"]:
            # No se avanza ultimaSync: el proximo ciclo reintenta la ventana.
            log.warning("Reloj %s: %s ventanas incompletas, no se avanza ultimaSync",
                        reloj_ip, len(resultado["ventanasTruncadas"]))
            db.commit()
            return resultado

        previo = ultima_sync(db, reloj_ip)
        if previo is None or ahora > previo:
            marcar_sync_ok(db, reloj_ip, ahora)
        db.commit()
    except Exception as e:
        resultado["error"] = str(e)
        marcar_sync_error(db, reloj_ip, str(e))
        db.commit()
        log.warning("Reloj %s: sync fallida: %s", reloj_ip, e)

    return resultado


def sincronizar_todos(db: Session, desde: Optional[datetime] = None,
                      hasta: Optional[datetime] = None) -> list[dict]:
    """Sincroniza todos los relojes configurados, cada uno de forma independiente."""
    ensure_tables(db)
    return [sincronizar_reloj(db, ip, desde, hasta) for ip in relojes_configurados()]
