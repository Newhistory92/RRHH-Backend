"""
Diagnostico de solo lectura: que codigos minor emiten realmente los relojes.

El sync filtra por minor=38 tanto en la consulta al equipo como al extraer.
Este script consulta SIN ese filtro para ver que eventos se estan perdiendo.

Usa pedir() del cliente ISAPI, que sigue validando la allowlist de solo
lectura: solo hace POST a /ISAPI/AccessControl/AcsEvent.

Uso:
    py scripts/diagnostico_minor_codes.py            (hoy, todos)
    py scripts/diagnostico_minor_codes.py 264        (hoy, solo ese ID)
"""

import os
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.services.isapi_client import ENDPOINT_ACS_EVENT, pedir, relojes_configurados

MAX_RESULTS = 100
MAX_PAGINAS = 200


# El equipo rechaza major sin minor con HTTP 400. Se prueban variantes hasta
# dar con la que acepta: en ISAPI el 0 suele significar "todos".
VARIANTES = [
    ("major=5 minor=0", {"major": 5, "minor": 0}),
    ("major=0 minor=0", {"major": 0, "minor": 0}),
    ("sin major/minor", {}),
]


def eventos_sin_filtro_minor(ip, desde, hasta):
    """
    Todos los eventos de la ventana sin filtrar por minor. Devuelve
    (etiqueta_variante, eventos).
    """
    ultimo_error = None
    for etiqueta, filtro in VARIANTES:
        posicion = 0
        todos = []
        try:
            for _ in range(MAX_PAGINAS):
                cond = {
                    "AcsEventCond": {
                        "searchID": "rrhh-diag",
                        "searchResultPosition": posicion,
                        "maxResults": MAX_RESULTS,
                        "startTime": desde.strftime("%Y-%m-%dT%H:%M:%S-03:00"),
                        "endTime": hasta.strftime("%Y-%m-%dT%H:%M:%S-03:00"),
                        **filtro,
                    }
                }
                payload = pedir("POST", ip, ENDPOINT_ACS_EVENT, cond)
                ev = (payload or {}).get("AcsEvent") or {}
                todos.extend(ev.get("InfoList") or [])
                if ev.get("responseStatusStrg") != "MORE":
                    break
                posicion += ev.get("numOfMatches", MAX_RESULTS)
            return etiqueta, todos
        except Exception as e:
            ultimo_error = f"{etiqueta}: {e}"
    raise RuntimeError(f"ninguna variante funciono. Ultimo error -> {ultimo_error}")


def main():
    bio_buscado = sys.argv[1] if len(sys.argv) > 1 else None
    hoy = date.today()
    desde = datetime.combine(hoy, time.min)
    hasta = datetime.combine(hoy + timedelta(days=1), time.min)

    for ip in relojes_configurados():
        print()
        print("=" * 70)
        print(f"RELOJ {ip} — eventos major=5 del {hoy}, SIN filtro de minor")
        print("=" * 70)

        try:
            variante, eventos = eventos_sin_filtro_minor(ip, desde, hasta)
        except Exception as e:
            print(f"  [ERROR] {e}")
            continue

        print(f"  Variante aceptada por el equipo: {variante}")
        print(f"  Total de eventos devueltos: {len(eventos)}")

        conteo = Counter(ev.get("minor") for ev in eventos)
        print()
        print("  Distribucion por minor:")
        for minor, n in sorted(conteo.items(), key=lambda x: -x[1]):
            captura = "  <-- el sync SOLO captura este" if minor == 38 else ""
            print(f"     minor={minor:<6} n={n}{captura}")

        con_persona = [
            ev for ev in eventos
            if str(ev.get("employeeNoString") or "").strip()
        ]
        print()
        print(f"  Eventos con employeeNoString: {len(con_persona)}")
        capturados = [ev for ev in con_persona if ev.get("minor") == 38]
        print(f"  De esos, capturados por el sync (minor=38): {len(capturados)}")
        print(f"  PERDIDOS por el filtro: {len(con_persona) - len(capturados)}")

        if bio_buscado:
            print()
            print(f"  --- Eventos de employeeNoString={bio_buscado} ---")
            propios = [
                ev for ev in con_persona
                if str(ev.get("employeeNoString")).strip() == bio_buscado
            ]
            if not propios:
                print("     (ninguno en la ventana)")
            for ev in sorted(propios, key=lambda e: e.get("time") or ""):
                estado = "CAPTURADO" if ev.get("minor") == 38 else "PERDIDO  "
                print(f"     {estado}  {ev.get('time')}  minor={ev.get('minor'):<5} "
                      f"verify={ev.get('currentVerifyMode')}  serial={ev.get('serialNo')}")


if __name__ == "__main__":
    main()
