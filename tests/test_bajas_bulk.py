"""
La baja vigente en el listado de empleados, sin N+1.

app/routes/rrhh.py arma el listado con 1 query principal + N queries bulk
(ver su docstring). Estas pruebas cubren la pieza bulk de "baja" sin fakear
la query principal completa (36 columnas por fila): bajas_bulk trae todas las
bajas de los empleados pedidos en UNA sola consulta y las agrupa por
employeeId, y baja_para_respuesta arma el valor {motivo, fechaBaja} o None a
partir de ese agrupado: informa la baja abierta (programada o vigente) y
usa baja_vigente como unica definicion de "esta de baja".
"""

from datetime import date

from app.database.bajas import bajas_bulk, baja_para_respuesta
from tests.fakes import FakeSession

HOY = date(2026, 9, 18)


def test_bajas_bulk_hace_una_sola_consulta_sin_importar_los_ids():
    db = FakeSession({"FROM EmployeeBaja": [
        {"employeeId": 8, "motivo": "Renuncia", "fechaBaja": date(2026, 9, 1),
         "fechaReingreso": None},
    ]})
    bajas_bulk(db, [8, 9, 10, 11, 12])
    ejecuciones_baja = [sql for sql, _ in db.ejecutadas if "FROM EmployeeBaja" in sql]
    assert len(ejecuciones_baja) == 1


def test_bajas_bulk_agrupa_por_employeeId():
    db = FakeSession({"FROM EmployeeBaja": [
        {"employeeId": 8, "motivo": "Renuncia", "fechaBaja": date(2026, 9, 1),
         "fechaReingreso": None},
        {"employeeId": 8, "motivo": "Despido", "fechaBaja": date(2020, 1, 1),
         "fechaReingreso": date(2020, 6, 1)},
        {"employeeId": 9, "motivo": "Jubilación", "fechaBaja": date(2026, 1, 1),
         "fechaReingreso": None},
    ]})
    grupo = bajas_bulk(db, [8, 9, 10])
    assert len(grupo[8]) == 2
    assert len(grupo[9]) == 1
    assert grupo.get(10, []) == []


def test_baja_para_respuesta_devuelve_motivo_y_fecha_para_una_baja_vigente():
    grupo = {8: [{"motivo": "Renuncia", "fechaBaja": date(2026, 9, 1),
                   "fechaReingreso": None}]}
    assert baja_para_respuesta(grupo, 8, HOY) == {
        "motivo": "Renuncia", "fechaBaja": "2026-09-01", "vigente": True,
    }


def test_baja_para_respuesta_devuelve_none_sin_baja():
    grupo = {}
    assert baja_para_respuesta(grupo, 8, HOY) is None


def test_baja_para_respuesta_informa_la_programada_como_no_vigente():
    """La programada tambien viaja: es la que RRHH puede cancelar desde el
    perfil antes de que llegue el dia."""
    grupo = {8: [{"motivo": "Renuncia", "fechaBaja": date(2026, 12, 1),
                   "fechaReingreso": None}]}
    assert baja_para_respuesta(grupo, 8, HOY) == {
        "motivo": "Renuncia", "fechaBaja": "2026-12-01", "vigente": False,
    }


def test_baja_para_respuesta_devuelve_none_con_baja_reincorporada():
    grupo = {8: [{"motivo": "Renuncia", "fechaBaja": date(2026, 1, 1),
                   "fechaReingreso": date(2026, 2, 1)}]}
    assert baja_para_respuesta(grupo, 8, HOY) is None
