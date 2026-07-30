"""
Sincronizacion de marcaciones desde los relojes hacia SQL Server.

AcsEvent filtra por startTime/endTime y no admite "serialNo mayor a", asi que
el sync no usa un cursor de correlativo sino una ventana temporal con solape.
El solape cubre desfasajes de hora y eventos registrados con retraso; los
duplicados que genera los descarta la unicidad (relojIp, serialNo), lo que hace
que reprocesar una ventana sea inofensivo.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

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


def sincronizar_reloj(db: Session, reloj_ip: str,
                     desde: Optional[datetime] = None,
                     hasta: Optional[datetime] = None) -> dict:
    """
    Sincroniza un equipo. Nunca propaga excepcion: un reloj caido se registra
    en RelojSync.ultimoError y no debe tumbar el job ni el otro equipo.
    """
    registrar_reloj(db, reloj_ip)
    ahora = hasta or datetime.now()
    if desde is None:
        desde, ahora = calcular_ventana(ultima_sync(db, reloj_ip), ahora)

    resultado = {"relojIp": reloj_ip, "leidos": 0, "insertados": 0, "error": None}
    previo_max = max_serial_no(db, reloj_ip)

    try:
        posicion = 0
        max_visto = 0
        for _ in range(MAX_PAGINAS):
            payload = buscar_eventos(reloj_ip, desde, ahora, posicion, MAX_RESULTS)
            filas = extraer_marcaciones(payload, reloj_ip)
            resultado["leidos"] += len(filas)
            if filas:
                resultado["insertados"] += insertar_marcaciones(db, filas)
                max_visto = max(max_visto, max(f["serialNo"] for f in filas))
            if not hay_mas_paginas(payload):
                break
            posicion += MAX_RESULTS

        # Riesgo conocido: si el equipo reinicia su correlativo, los eventos
        # nuevos colisionarian con los viejos y se descartarian en silencio.
        if previo_max is not None and max_visto and max_visto < previo_max:
            log.warning(
                "Reloj %s: serialNo maximo recibido (%s) es menor al almacenado (%s). "
                "Posible reinicio del correlativo: las marcaciones nuevas podrian "
                "estar descartandose por la unicidad.",
                reloj_ip, max_visto, previo_max,
            )

        marcar_sync_ok(db, reloj_ip, ahora)
        db.commit()
    except ISAPIError as e:
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
