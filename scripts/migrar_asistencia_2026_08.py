"""
Migracion unica del modulo de asistencia, agosto 2026.

1. Crea las tablas nuevas y aplica los cambios de esquema.
2. Mueve fechaInicioModulo del 30/06 al 30/07.
3. Corre el primer backfill.

El paso 2 se hace aca y no en ensure_tables a proposito: si corriera en cada
arranque, volveria a empujar la fecha hacia adelante cada vez que RRHH la mueva
hacia atras despues de recuperar historico de los relojes.

Motivo del cambio de fecha: la carga inicial del 30/07 pidio 30 dias en una
sola llamada y los equipos devolvieron una fraccion. En el periodo 30/06-29/07
se capturo el 7,4% del rango de correlativos, contra el 25% del sync
incremental posterior. Calcular saldos sobre ese mes produciria ausencias y
jornadas incompletas falsas para casi todo el personal.

Uso:
    py scripts/migrar_asistencia_2026_08.py
"""

import os
import sys

# Asegurar que la raiz del proyecto esta en sys.path sin importar desde donde
# se corra el script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from sqlalchemy import text

from app.database.asistencia import ensure_tables, get_config
from app.database.database import SessionLocal
from app.services.asistencia_recalc import recalcular_todos

FECHA_INICIO_NUEVA = date(2026, 7, 30)


def main() -> int:
    db = SessionLocal()
    try:
        print("[1/3] Creando tablas y aplicando cambios de esquema...")
        ensure_tables(db)
        print("      OK")

        print(f"[2/3] Moviendo fechaInicioModulo a {FECHA_INICIO_NUEVA}...")
        antes = get_config(db)["fechaInicioModulo"]
        db.execute(text("""
            UPDATE AsistenciaConfig
            SET fechaInicioModulo = :fecha, updatedAt = GETDATE()
            WHERE id = 1
        """), {"fecha": FECHA_INICIO_NUEVA})
        db.commit()
        print(f"      {antes} -> {get_config(db)['fechaInicioModulo']}")

        print(f"[3/3] Backfill del anio {FECHA_INICIO_NUEVA.year}...")
        resultado = recalcular_todos(db, FECHA_INICIO_NUEVA.year, origen="manual")
        print(f"      {resultado['procesados']} empleados, "
              f"{resultado['filas']} jornadas, "
              f"{len(resultado['errores'])} errores")
        for e in resultado["errores"]:
            print(f"      ERROR empleado {e['employeeId']}: {e['error']}")

        return 1 if resultado["errores"] else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
