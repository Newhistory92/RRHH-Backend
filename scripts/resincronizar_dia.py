"""
Re-sincronizacion manual de un rango de fechas desde los relojes biometricos.

Uso:
    py scripts/resincronizar_dia.py 2026-08-03
    py scripts/resincronizar_dia.py 2026-08-03 2026-08-03
"""

import sys
import os
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.database import SessionLocal
from app.services.reloj_sync import sincronizar_todos

def main():
    args = sys.argv[1:]
    if not args:
        print("Uso: py scripts/resincronizar_dia.py YYYY-MM-DD [YYYY-MM-DD]")
        sys.exit(1)

    try:
        desde = date.fromisoformat(args[0])
        hasta = date.fromisoformat(args[1]) if len(args) > 1 else desde
    except ValueError as e:
        print(f"Fecha invalida: {e}")
        sys.exit(1)

    desde_dt = datetime(desde.year, desde.month, desde.day, 0, 0, 0)
    hasta_dt = datetime(hasta.year, hasta.month, hasta.day, 23, 59, 59)

    print(f"Resincronizando {desde} a {hasta} ...")
    db = SessionLocal()
    try:
        resultados = sincronizar_todos(db, desde=desde_dt, hasta=hasta_dt)
        for r in resultados:
            if r.get("error"):
                print(f"  [ERROR] {r['relojIp']}: {r['error']}")
            else:
                print(f"  [OK] {r['relojIp']}: {r['insertados']} nuevas, "
                      f"{r.get('ventanasTruncadas', 0)} ventanas truncadas")
    finally:
        db.close()

if __name__ == "__main__":
    main()
