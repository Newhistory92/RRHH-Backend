"""
Diagnostico de solo lectura del pipeline de asistencia.

Mide cada capa por separado para ubicar donde se corta el flujo:
    reloj -> Marcacion -> Employee.biometricoId -> JornadaDiaria

No escribe nada ni consulta los relojes. Solo lee la base.

Uso:
    py scripts/diagnostico_marcaciones.py 264
"""

import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.database.database import SessionLocal

DIAS = 4


def titulo(texto):
    print()
    print("=" * 70)
    print(texto)
    print("=" * 70)


def main():
    bio_buscado = sys.argv[1] if len(sys.argv) > 1 else "264"
    desde = datetime.combine(date.today() - timedelta(days=DIAS), datetime.min.time())

    db = SessionLocal()
    try:
        titulo("1. ESTADO DE SINCRONIZACION (RelojSync)")
        filas = db.execute(text(
            "SELECT relojIp, ultimaSync, ultimoError, activo FROM RelojSync ORDER BY relojIp"
        )).mappings().all()
        if not filas:
            print("  (sin filas: ningun reloj registrado todavia)")
        for f in filas:
            print(f"  {f['relojIp']:<18} ultimaSync={f['ultimaSync']} "
                  f"activo={f['activo']}")
            if f["ultimoError"]:
                print(f"      ultimoError: {f['ultimoError']}")

        titulo(f"2. MARCACIONES DE TODOS LOS IDs (ultimos {DIAS} dias)")
        filas = db.execute(text("""
            SELECT biometricoId,
                   COUNT(*)        AS cantidad,
                   MIN(fechaHora)  AS primera,
                   MAX(fechaHora)  AS ultima,
                   MIN(serialNo)   AS serialMin,
                   MAX(serialNo)   AS serialMax
            FROM Marcacion
            WHERE fechaHora >= :desde
            GROUP BY biometricoId
            ORDER BY ultima DESC
        """), {"desde": desde}).mappings().all()
        if not filas:
            print("  (NINGUNA marcacion en la ventana: el sync no esta trayendo nada)")
        for f in filas:
            marca = " <-- BUSCADO" if str(f["biometricoId"]) == bio_buscado else ""
            print(f"  bio={f['biometricoId']:<10} n={f['cantidad']:<4} "
                  f"{f['primera']} .. {f['ultima']}  "
                  f"serial {f['serialMin']}-{f['serialMax']}{marca}")

        titulo(f"3. DETALLE DE MARCACIONES DE bio={bio_buscado}")
        filas = db.execute(text("""
            SELECT id, relojIp, serialNo, biometricoId, fechaHora, verifyMode, createdAt
            FROM Marcacion
            WHERE biometricoId = :bio AND fechaHora >= :desde
            ORDER BY fechaHora
        """), {"bio": bio_buscado, "desde": desde}).mappings().all()
        if not filas:
            print(f"  (ninguna marcacion con biometricoId='{bio_buscado}')")
        for f in filas:
            print(f"  {f['fechaHora']}  serial={f['serialNo']:<10} "
                  f"reloj={f['relojIp']:<18} verify={f['verifyMode']} "
                  f"insertada={f['createdAt']}")

        titulo("4. EMPLEADOS CON biometricoId CARGADO")
        filas = db.execute(text("""
            SELECT id, name, dni, biometricoId, cronogramaId, horas
            FROM Employee
            WHERE biometricoId IS NOT NULL
            ORDER BY id
        """)).mappings().all()
        if not filas:
            print("  (ningun empleado tiene biometricoId cargado)")
        for f in filas:
            print(f"  id={f['id']:<5} bio='{f['biometricoId']}' "
                  f"cronogramaId={f['cronogramaId']} horas={f['horas']}  {f['name']}")

        titulo("5. CONFIGURACION DEL MODULO")
        fila = db.execute(text(
            "SELECT * FROM AsistenciaConfig WHERE id = 1"
        )).mappings().first()
        if fila is None:
            print("  (sin fila de configuracion)")
        else:
            for clave, valor in dict(fila).items():
                print(f"  {clave} = {valor}")

        titulo(f"6. JORNADAS CALCULADAS (ultimos {DIAS} dias)")
        filas = db.execute(text("""
            SELECT j.employeeId, e.name, e.biometricoId, j.fecha, j.estado,
                   j.entrada, j.salida, j.horasTrabajadas, j.saldoDia
            FROM JornadaDiaria j
            LEFT JOIN Employee e ON e.id = j.employeeId
            WHERE j.fecha >= :desde
            ORDER BY j.fecha, j.employeeId
        """), {"desde": desde.date()}).mappings().all()
        if not filas:
            print("  (ninguna jornada calculada en la ventana)")
        for f in filas:
            print(f"  {f['fecha']}  emp={f['employeeId']:<5} bio={f['biometricoId']} "
                  f"{f['estado']:<12} in={f['entrada']} out={f['salida']} "
                  f"saldo={f['saldoDia']}  {f['name']}")

        titulo("7. HORARIO ASIGNADO AL EMPLEADO BUSCADO")
        filas = db.execute(text("""
            SELECT e.id, e.name, e.biometricoId, e.cronogramaId,
                   h.horaInicio, h.horaFin, h.horasTrabajo
            FROM Employee e
            LEFT JOIN Horario h ON h.id = e.cronogramaId
            WHERE e.biometricoId = :bio
        """), {"bio": bio_buscado}).mappings().all()
        if not filas:
            print(f"  (ningun empleado tiene biometricoId='{bio_buscado}')")
        for f in filas:
            print(f"  id={f['id']} {f['name']}")
            print(f"     cronogramaId={f['cronogramaId']} "
                  f"horaInicio={f['horaInicio']} horaFin={f['horaFin']} "
                  f"horasTrabajo={f['horasTrabajo']}")

        titulo("8. RANGO GLOBAL DE LA TABLA Marcacion")
        fila = db.execute(text("""
            SELECT COUNT(*) AS total, MIN(fechaHora) AS primera,
                   MAX(fechaHora) AS ultima, MAX(createdAt) AS ultimaInsercion
            FROM Marcacion
        """)).mappings().first()
        print(f"  total={fila['total']}  rango {fila['primera']} .. {fila['ultima']}")
        print(f"  ultima insercion en la base: {fila['ultimaInsercion']}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
