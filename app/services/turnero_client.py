"""
Cliente del endpoint de metricas de Turnero.

Turnero calcula su propia productividad -atendidos, validas, breves,
anomalias y desvio contra la mediana del tramite- y RRHH la consume en vez de
rehacerla: dos implementaciones de la misma metrica se separan con el tiempo y
despues nadie sabe cual es la buena.

Turnero es una fuente secundaria. Que no responda deja la dimension operativa
en "sin datos", nunca tumba la ficha ni la pantalla.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date

import requests

log = logging.getLogger(__name__)

TURNERO_URL = os.getenv("TURNERO_URL", "").rstrip("/")
TURNERO_TOKEN = os.getenv("TURNERO_SERVICE_TOKEN", "")
TIMEOUT_SEG = 10


@dataclass(frozen=True)
class MetricaTurnero:
    """Productividad de un operador en un rango, tal como la calcula Turnero."""
    dniInstitucional: str
    atendidos: int
    validas: int
    breves: int
    anomalias: int
    promedioSegundos: float | None
    desvioContraMedianaSegundos: float | None
    horasBox: float


def parsear_metricas(payload: dict) -> dict[str, MetricaTurnero]:
    """
    Traduce la respuesta del endpoint a un mapa por DNI.

    Se indexa por dniInstitucional y no por el id interno de Turnero porque el
    DNI es la clave con la que se vincula contra Employee: un identificador del
    mundo real, verificable, que no depende de como se creo cada cuenta.

    Funcion pura, sin I/O.
    """
    resultado: dict[str, MetricaTurnero] = {}
    for fila in payload.get("empleados", []):
        dni = fila.get("dniInstitucional")
        if not dni:
            continue
        resultado[str(dni).strip()] = MetricaTurnero(
            dniInstitucional=str(dni).strip(),
            atendidos=int(fila.get("atendidos") or 0),
            validas=int(fila.get("validas") or 0),
            breves=int(fila.get("breves") or 0),
            anomalias=int(fila.get("anomalias") or 0),
            promedioSegundos=fila.get("promedioSegundos"),
            desvioContraMedianaSegundos=fila.get("desvioContraMedianaSegundos"),
            horasBox=float(fila.get("horasBox") or 0),
        )
    return resultado


def obtener_metricas(desde: date, hasta: date) -> dict[str, MetricaTurnero]:
    """
    Pide las metricas del rango. Devuelve {} si Turnero no esta disponible.

    El {} no se distingue de "nadie atendio nada", y esta bien: en los dos
    casos la ficha muestra la dimension operativa como sin datos, que es lo
    honesto. Lo que no puede pasar es que la pantalla se caiga porque una
    fuente secundaria no respondio.
    """
    if not TURNERO_URL or not TURNERO_TOKEN:
        return {}
    try:
        resp = requests.get(
            f"{TURNERO_URL}/api/metricas/empleados",
            params={"desde": desde.isoformat(), "hasta": hasta.isoformat()},
            headers={"Authorization": f"Bearer {TURNERO_TOKEN}"},
            timeout=TIMEOUT_SEG,
        )
        resp.raise_for_status()
        return parsear_metricas(resp.json())
    except Exception as e:
        log.warning("Aviso: no se pudieron traer las metricas de Turnero: %s", e)
        return {}
