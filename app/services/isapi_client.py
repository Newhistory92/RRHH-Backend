"""
Cliente ISAPI de SOLO LECTURA para relojes Hikvision DS-K1T320MFWX.

Garantia dura del subsistema: este modulo es el unico punto de acceso a los
equipos. Requisito explicito del usuario -- "no quiero modificar nada del reloj,
solo absorber la informacion".

En ISAPI el verbo HTTP no indica si la operacion escribe: las busquedas usan
POST porque el filtro viaja en el cuerpo. Por eso la garantia no puede apoyarse
en el verbo y se implementa como allowlist cerrada de (metodo, path).
"""

import os
from datetime import datetime
from typing import Optional

import requests
from requests.auth import HTTPDigestAuth

ENDPOINT_DEVICE_INFO = "/ISAPI/System/deviceInfo"
ENDPOINT_ACS_EVENT = "/ISAPI/AccessControl/AcsEvent"
ENDPOINT_USER_SEARCH = "/ISAPI/AccessControl/UserInfo/Search"

# Unicos endpoints invocables. Deliberadamente excluidos por escribir en el
# equipo: UserInfo/Record, UserInfo/Modify, UserInfo/Delete,
# RemoteControl/door/*, System/time, ClearEvent y todo PUT de configuracion.
ALLOWLIST = {
    ("GET", ENDPOINT_DEVICE_INFO),
    ("POST", ENDPOINT_ACS_EVENT),
    ("POST", ENDPOINT_USER_SEARCH),
}

TIMEOUT_SEGUNDOS = 15


class ISAPIError(Exception):
    """Fallo al comunicarse con un reloj."""


class ISAPINotAllowed(ISAPIError):
    """Se intento una operacion fuera de la allowlist de solo lectura."""


def _credenciales() -> HTTPDigestAuth:
    usuario = os.getenv("RELOJ_USER")
    clave = os.getenv("RELOJ_PASS")
    if not usuario or not clave:
        raise ISAPIError("RELOJ_USER / RELOJ_PASS no estan configurados en el .env")
    return HTTPDigestAuth(usuario, clave)


def relojes_configurados() -> list[str]:
    """IPs de los relojes, desde RELOJ_IPS separadas por coma."""
    crudo = os.getenv("RELOJ_IPS", "")
    return [ip.strip() for ip in crudo.split(",") if ip.strip()]


def pedir(metodo: str, ip: str, path: str, json_body: Optional[dict] = None) -> "dict | str":
    """
    Unica salida a la red hacia un reloj. Rechaza cualquier par (metodo, path)
    que no este en la allowlist ANTES de abrir la conexion.
    """
    if (metodo, path) not in ALLOWLIST:
        raise ISAPINotAllowed(
            f"{metodo} {path} no esta en la allowlist de solo lectura del cliente ISAPI"
        )

    url = f"http://{ip}{path}"
    if json_body is not None:
        url += "?format=json"

    try:
        resp = requests.request(
            metodo, url, auth=_credenciales(), json=json_body, timeout=TIMEOUT_SEGUNDOS
        )
    except requests.RequestException as e:
        raise ISAPIError(f"Reloj {ip} inaccesible: {e}") from e

    if resp.status_code == 401:
        raise ISAPIError(f"Reloj {ip}: credenciales rechazadas (401)")
    if resp.status_code >= 400:
        raise ISAPIError(f"Reloj {ip}: HTTP {resp.status_code}")

    if json_body is None:
        return resp.text
    try:
        return resp.json()
    except ValueError as e:
        raise ISAPIError(f"Reloj {ip}: respuesta JSON malformada") from e


def buscar_eventos(ip: str, desde: datetime, hasta: datetime,
                   posicion: int, max_results: int = 100) -> dict:
    """
    Busca marcaciones validas en una ventana. El filtro major/minor va DENTRO
    de AcsEventCond para que filtre el equipo y no viajen los eventos de puerta.
    """
    cond = {
        "AcsEventCond": {
            "searchID": "rrhh-sync",
            "searchResultPosition": posicion,
            "maxResults": max_results,
            "major": 5,
            "minor": 38,
            "startTime": desde.strftime("%Y-%m-%dT%H:%M:%S-03:00"),
            "endTime": hasta.strftime("%Y-%m-%dT%H:%M:%S-03:00"),
        }
    }
    return pedir("POST", ip, ENDPOINT_ACS_EVENT, cond)


def buscar_usuario(ip: str, biometrico_id: str) -> Optional[dict]:
    """Datos de una persona del padron del reloj, o None si no existe."""
    cond = {
        "UserInfoSearchCond": {
            "searchID": "rrhh-lookup",
            "searchResultPosition": 0,
            "maxResults": 30,
            "EmployeeNoList": [{"employeeNo": str(biometrico_id)}],
        }
    }
    data = pedir("POST", ip, ENDPOINT_USER_SEARCH, cond)
    usuarios = (data.get("UserInfoSearch") or {}).get("UserInfo") or []
    for u in usuarios:
        if str(u.get("employeeNo")) == str(biometrico_id):
            return u
    return None


def info_dispositivo(ip: str) -> str:
    """XML crudo de deviceInfo. Se usa como health check."""
    return pedir("GET", ip, ENDPOINT_DEVICE_INFO)
